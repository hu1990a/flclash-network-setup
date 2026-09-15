#!/usr/bin/env python3
"""Low-noise FlClash network guard with redacted state and actionable alerts."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import sys
import time
from typing import Any


DEFAULT_EXTERNAL_ENDPOINT = "https://ifconfig.co/json"
SENSITIVE_KEYS = {"ip", "query", "public_ip", "address", "hostname"}
IPV4_PATTERN = re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?![\d.])")


def sanitize_for_storage(value: Any) -> Any:
    """Remove public-IP fields and redact IPv4 literals before output or storage."""
    if isinstance(value, dict):
        return {
            str(key): sanitize_for_storage(item)
            for key, item in value.items()
            if not _is_sensitive_key(str(key))
        }
    if isinstance(value, list):
        return [sanitize_for_storage(item) for item in value]
    if isinstance(value, str):
        return IPV4_PATTERN.sub("[REDACTED_IP]", value)
    return value


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return lowered in SENSITIVE_KEYS or lowered.startswith("ip_") or lowered.endswith("_ip")


def _alert(code: str, severity: str, title: str, action: str, reason: str) -> dict[str, str]:
    return {
        "code": code,
        "severity": severity,
        "title": title,
        "recommended_action": action,
        "reason": reason,
    }


def _exit_signature(exit_info: Any) -> tuple[str, str]:
    if not isinstance(exit_info, dict):
        return "", ""
    country = str(exit_info.get("country") or exit_info.get("country_iso") or "").upper()
    asn = str(exit_info.get("asn") or exit_info.get("as_number") or "").upper()
    return country, asn


def evaluate_observation(observation: dict[str, Any]) -> list[dict[str, str]]:
    """Turn a local/external observation into clear, actionable abnormal events."""
    alerts: list[dict[str, str]] = []
    if observation.get("proxy_listening") is False:
        alerts.append(
            _alert(
                "PROXY_DOWN",
                "critical",
                "FlClash 本地代理未就绪",
                "启动或重启 FlClash，确认已载入订阅和系统代理，再点一次“立即检查”。",
                "本地代理端口没有监听，Claude/Codex CLI 可能无法联网；未受守卫保护的程序也可能直连。",
            )
        )
    if observation.get("tun_enabled") is False:
        alerts.append(
            _alert(
                "TUN_OFF",
                "warning",
                "FlClash TUN 未开启",
                "在 FlClash 设置中打开 TUN，按提示允许辅助服务，然后完全退出并重开 FlClash。",
                "未读取代理环境变量的程序可能绕过本地代理，IPv6 也更容易出现出口不一致。",
            )
        )

    proxy_country, proxy_asn = _exit_signature(observation.get("proxy_exit"))
    ipv6_country, ipv6_asn = _exit_signature(observation.get("direct_ipv6"))
    if proxy_country and ipv6_country:
        country_mismatch = proxy_country != ipv6_country
        asn_mismatch = bool(proxy_asn and ipv6_asn and proxy_asn != ipv6_asn)
        if country_mismatch or asn_mismatch:
            alerts.append(
                _alert(
                    "IPV6_BYPASS",
                    "critical" if country_mismatch else "warning",
                    "IPv6 出口与代理出口不一致",
                    "先确认 TUN 已开启且当前订阅含 ipv6: false，重连网络后复测；仍异常再运行完整检查并决定是否严格关闭 IPv6。",
                    "系统 IPv6 的出口国家或网络运营商与代理出口不同，存在部分连接绕过代理的可能。",
                )
            )

    current_exit = _exit_signature(observation.get("proxy_exit"))
    previous_exit = _exit_signature(observation.get("previous_proxy_exit"))
    if all(current_exit) and all(previous_exit) and current_exit != previous_exit:
        alerts.append(
            _alert(
                "EXIT_CHANGED",
                "warning",
                "代理出口发生变化",
                "确认 FlClash 当前界面节点是否符合预期；登录或操作敏感账号前，固定到已测试的稳定节点并再次检查。",
                "出口国家或网络运营商已变化，短时间频繁变更可能触发平台的异常登录或风控检查。",
            )
        )
    return alerts


def render_notification(alert: dict[str, str]) -> dict[str, str]:
    return {
        "title": f"FlClash 网络提醒：{alert['title']}",
        "body": f"推荐操作：{alert['recommended_action']}\n原因：{alert['reason']}",
    }


def confirm_alerts(
    state: dict[str, Any], alerts: list[dict[str, str]], required: int = 2
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """Require repeated observations and notify only once until recovery."""
    required = max(1, int(required))
    current_codes = {item["code"] for item in alerts}
    previous = dict(state.get("consecutive") or {})
    notified = set(state.get("notified") or [])
    consecutive: dict[str, int] = {}
    ready: list[dict[str, str]] = []
    for alert in alerts:
        code = alert["code"]
        count = int(previous.get(code, 0)) + 1
        consecutive[code] = count
        if count >= required and code not in notified:
            ready.append(alert)
            notified.add(code)
    notified.intersection_update(current_codes)
    state = dict(state)
    state["consecutive"] = consecutive
    state["notified"] = sorted(notified)
    return state, ready


def should_run_external_check(
    *,
    consent: bool,
    last_checked_at: float,
    now: float,
    interval_seconds: int,
    network_changed: bool,
) -> bool:
    if not consent:
        return False
    due = now - float(last_checked_at or 0) >= max(60, int(interval_seconds))
    return due and (network_changed or not last_checked_at)


def _default_preferences_paths() -> list[Path]:
    if os.name == "nt":
        appdata = Path(os.environ.get("APPDATA", ""))
        return [appdata / "com.follow" / "clash" / "shared_preferences.json"]
    home = Path.home()
    return [
        home / "Library/Application Support/com.follow.clash/shared_preferences.json",
        home / "Library/Application Support/com.follow/clash/shared_preferences.json",
    ]


def read_flclash_state(config: dict[str, Any]) -> dict[str, Any]:
    configured = config.get("flclash_preferences")
    paths = [Path(configured).expanduser()] if configured else _default_preferences_paths()
    result: dict[str, Any] = {
        "port": int(config.get("default_port", 7890)),
        "tun_enabled": None,
        "system_proxy": None,
        "preferences_found": False,
        "fingerprint": "missing",
    }
    for path in paths:
        if not path.is_file():
            continue
        result["preferences_found"] = True
        try:
            outer = json.loads(path.read_text(encoding="utf-8-sig"))
            raw = outer.get("flutter.config", {})
            inner = json.loads(raw) if isinstance(raw, str) else raw
            patch = inner.get("patchClashConfig") or {}
            port = patch.get("mixed-port")
            if isinstance(port, int) or (isinstance(port, str) and port.isdigit()):
                result["port"] = int(port)
            result["tun_enabled"] = (inner.get("vpnProps") or {}).get("enable")
            result["system_proxy"] = (inner.get("networkProps") or {}).get("systemProxy")
            profile_id = str(inner.get("currentProfileId") or "")
            stat = path.stat()
            result["fingerprint"] = f"{profile_id}:{result['port']}:{result['tun_enabled']}:{stat.st_mtime_ns}"
        except (OSError, ValueError, TypeError):
            result["fingerprint"] = "unreadable"
        break
    return result


def port_is_listening(port: int, timeout: float = 0.8) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def _curl_json(arguments: list[str], timeout_seconds: int) -> dict[str, Any] | None:
    command = ["curl", "--silent", "--show-error", "--fail", "--max-time", str(timeout_seconds)]
    completed = subprocess.run(
        command + arguments,
        capture_output=True,
        text=True,
        timeout=timeout_seconds + 3,
        check=False,
    )
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def collect_external_observation(config: dict[str, Any], port: int) -> dict[str, Any]:
    if not config.get("external_check_consent"):
        raise PermissionError("External IP checks require explicit consent")
    endpoint = str(config.get("external_endpoint") or DEFAULT_EXTERNAL_ENDPOINT)
    timeout = int(config.get("external_timeout_seconds", 10))
    proxy = f"http://127.0.0.1:{port}"
    return {
        "proxy_exit": _curl_json(["--proxy", proxy, endpoint], timeout),
        "direct_ipv4": _curl_json(["-4", "--noproxy", "*", endpoint], timeout),
        "direct_ipv6": _curl_json(["-6", "--noproxy", "*", endpoint], timeout),
    }


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else dict(default)
    except (OSError, ValueError):
        return dict(default)


def _system_network_fingerprint() -> str:
    """Hash local network state so adapter/IP changes are detected without storing it."""
    if os.name == "nt":
        command = ["ipconfig", "/all"]
    elif platform.system() == "Darwin":
        command = ["scutil", "--nwi"]
    else:
        command = ["ip", "address"]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=10,
            check=False,
        )
        material = completed.stdout + completed.stderr
    except (OSError, subprocess.SubprocessError):
        material = b"unavailable"
    return hashlib.sha256(material).hexdigest()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(sanitize_for_storage(value), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(path)


def _notify_windows(title: str, body: str) -> bool:
    escaped_title = html.escape(title)
    escaped_body = html.escape(body).replace("\n", "&#10;")
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "$x=New-Object Windows.Data.Xml.Dom.XmlDocument;"
        f"$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>{escaped_title}</text>"
        f"<text>{escaped_body}</text></binding></visual></toast>');"
        "$t=[Windows.UI.Notifications.ToastNotification]::new($x);"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Windows PowerShell').Show($t)"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return completed.returncode == 0


def _applescript_quote(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return '"' + escaped + '"'


def _notify_macos(title: str, body: str) -> bool:
    script = "display notification " + _applescript_quote(body) + " with title " + _applescript_quote(title)
    completed = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    return completed.returncode == 0


def send_notification(alert: dict[str, str]) -> bool:
    rendered = render_notification(alert)
    if os.name == "nt":
        return _notify_windows(rendered["title"], rendered["body"])
    if platform.system() == "Darwin":
        return _notify_macos(rendered["title"], rendered["body"])
    return False


def check_once(config_path: Path, *, notify: bool) -> dict[str, Any]:
    config = _read_json(config_path, {})
    state_path = Path(config.get("state_path") or config_path.with_name("state.json"))
    state = _read_json(state_path, {})
    flclash = read_flclash_state(config)
    observation: dict[str, Any] = {
        "proxy_listening": port_is_listening(flclash["port"]),
        "tun_enabled": flclash["tun_enabled"],
    }
    now = time.time()
    local_fingerprint = hashlib.sha256(
        (flclash["fingerprint"] + ":" + _system_network_fingerprint()).encode("utf-8")
    ).hexdigest()
    changed = local_fingerprint != state.get("local_fingerprint")
    if changed:
        state["external_check_pending"] = True
    if should_run_external_check(
        consent=bool(config.get("external_check_consent")),
        last_checked_at=float(state.get("last_external_check", 0)),
        now=now,
        interval_seconds=int(config.get("external_interval_seconds", 3600)),
        network_changed=bool(state.get("external_check_pending")),
    ):
        external = collect_external_observation(config, flclash["port"])
        observation.update(external)
        observation["previous_proxy_exit"] = state.get("last_proxy_exit")
        state["last_external_check"] = now
        state["last_proxy_exit"] = sanitize_for_storage(external.get("proxy_exit"))
        state["external_check_pending"] = False

    alerts = evaluate_observation(observation)
    state, ready = confirm_alerts(
        state,
        alerts,
        required=int(config.get("confirmations_required", 2)),
    )
    state["local_fingerprint"] = local_fingerprint
    state["last_check"] = now
    state["last_status"] = "ALERT" if alerts else "PASS"
    _write_json(state_path, state)
    delivery = []
    if notify:
        delivery = [{"code": item["code"], "delivered": send_notification(item)} for item in ready]
    return sanitize_for_storage(
        {
            "status": state["last_status"],
            "alerts": alerts,
            "notifications": delivery,
            "external_check": "ENABLED" if config.get("external_check_consent") else "DISABLED",
        }
    )


def run_guard(config_path: Path) -> int:
    config = _read_json(config_path, {})
    paused_path = Path(config.get("paused_path") or config_path.with_name("paused.flag"))
    interval = max(10, int(config.get("local_interval_seconds", 20)))
    while True:
        if not paused_path.exists():
            try:
                check_once(config_path, notify=True)
            except Exception:
                # The next cycle retries. Runtime exceptions are intentionally not written with network data.
                pass
        time.sleep(interval)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "check", "status"))
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--notify", action="store_true", help="Allow check mode to show confirmed alerts")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "run":
        return run_guard(args.config)
    if args.command == "status":
        config = _read_json(args.config, {})
        state_path = Path(config.get("state_path") or args.config.with_name("state.json"))
        print(json.dumps(sanitize_for_storage(_read_json(state_path, {"status": "NOT_RUN"})), ensure_ascii=False, indent=2))
        return 0
    report = check_once(args.config, notify=args.notify)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
