#!/usr/bin/env python3
"""Probe current FlClash candidates and emit a sanitized recommendation report."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Iterable


DEFAULT_CONTROLLER = "http://127.0.0.1:9090"
DEFAULT_DELAY_URL = "http://www.gstatic.com/generate_204"


def _field_map(output: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for line in re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", output).splitlines():
        match = re.match(r"^\s*║\s*([^│]+?)\s*│\s*(.*?)\s*║?\s*$", line)
        if match:
            fields[match.group(1).strip()] = match.group(2).strip()
    return fields


def parse_ipcheck_output(output: str) -> dict[str, object]:
    """Extract non-identifying security fields; never retain an IP address."""
    fields = _field_map(output)
    risk_text = fields.get("IP 风险查询", "")
    abuse_text = fields.get("垃圾滥用记录", "")
    risk_match = re.search(r"(\d+(?:\.\d+)?)/100", risk_text)
    abuse_match = re.search(r"举报\s*(\d+)\s*次", abuse_text)
    recent_match = re.search(r"最近举报\s*(\d{4}-\d{2}-\d{2})", output)
    type_match = re.search(r"类型\s+(.+?)(?:\s+已标记|$)", risk_text)
    timezone_text = fields.get("所处时区", "")
    timezone_match = re.search(r"([A-Za-z_+-]+/[A-Za-z_+-]+)", timezone_text)
    abuse_not_listed = "未收录" in abuse_text
    result: dict[str, object] = {
        "city": fields.get("城市") or None,
        "provider": fields.get("运营商") or None,
        "timezone": timezone_match.group(1) if timezone_match else None,
        "network_type": fields.get("机房 / 住宅") or None,
        "risk_score": float(risk_match.group(1)) if risk_match else None,
        "risk_type": type_match.group(1).strip() if type_match else None,
        "compromised": "compromised" in risk_text.lower(),
        "abuse_reports": 0 if abuse_not_listed else (int(abuse_match.group(1)) if abuse_match else None),
        "abuse_not_listed": abuse_not_listed,
        "last_reported": recent_match.group(1) if recent_match else None,
    }
    result["security_complete"] = (
        result["risk_score"] is not None and result["abuse_reports"] is not None
    )
    return result


def rank_results(results: Iterable[dict[str, object]]) -> list[dict[str, object]]:
    def value_or_inf(value: object) -> float:
        return float(value) if isinstance(value, (int, float)) else math.inf

    def key(item: dict[str, object]) -> tuple[object, ...]:
        rounds = int(item.get("rounds") or 0)
        successful = int(item.get("successful_rounds") or 0)
        fully_stable = rounds > 0 and successful == rounds
        return (
            not fully_stable,
            not bool(item.get("security_complete")),
            bool(item.get("compromised")),
            value_or_inf(item.get("risk_score")),
            value_or_inf(item.get("abuse_reports")),
            "" if item.get("abuse_reports") == 0 else str(item.get("last_reported") or "9999-99-99"),
            value_or_inf(item.get("median_delay_ms")),
            value_or_inf(item.get("jitter_ms")),
            str(item.get("candidate") or ""),
        )

    return sorted(results, key=key)


class ClashController:
    def __init__(self, base_url: str = DEFAULT_CONTROLLER):
        parsed = urllib.parse.urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("Controller must be a local HTTP endpoint")
        if parsed.port != 9090:
            raise ValueError("Controller must listen on local port 9090")
        self.base_url = base_url.rstrip("/")
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _json(self, path: str, method: str = "GET", payload: dict[str, str] | None = None) -> dict:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with self.opener.open(request, timeout=15) as response:
            body = response.read()
        return json.loads(body.decode("utf-8")) if body else {}

    def current(self, group: str) -> str:
        path = "/proxies/" + urllib.parse.quote(group, safe="")
        return str(self._json(path).get("now") or "")

    def switch(self, group: str, candidate: str) -> None:
        path = "/proxies/" + urllib.parse.quote(group, safe="")
        self._json(path, method="PUT", payload={"name": candidate})
        if self.current(group) != candidate:
            raise RuntimeError(f"FlClash did not select candidate: {candidate}")

    def delay(self, candidate: str, timeout_ms: int, delay_url: str) -> int:
        query = urllib.parse.urlencode({"timeout": timeout_ms, "url": delay_url})
        path = "/proxies/" + urllib.parse.quote(candidate, safe="") + "/delay?" + query
        value = self._json(path).get("delay")
        if not isinstance(value, int) or value <= 0:
            raise TimeoutError(candidate)
        return value


def probe_candidates(
    *,
    controller,
    group: str,
    candidates: list[str],
    rounds: int,
    timeout_ms: int,
    delay_url: str,
    ipcheck_runner: Callable[[str], str] | None,
    settle_seconds: float = 0.0,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict[str, object]:
    if rounds < 2:
        raise ValueError("At least two latency rounds are required for stability testing")
    if not candidates or len(set(candidates)) != len(candidates):
        raise ValueError("Candidates must be a non-empty unique list")

    original = controller.current(group)
    if not original:
        raise RuntimeError("Unable to record the original FlClash selection")
    results: list[dict[str, object]] = []
    restored = False
    try:
        for candidate in candidates:
            item: dict[str, object] = {
                "candidate": candidate,
                "rounds": rounds,
                "delay_samples_ms": [],
                "security_status": "SKIPPED",
                "security_complete": False,
                "compromised": False,
                "risk_score": None,
                "abuse_reports": None,
            }
            try:
                controller.switch(group, candidate)
                if settle_seconds > 0:
                    sleeper(settle_seconds)
                samples: list[int | None] = []
                for _ in range(rounds):
                    try:
                        samples.append(int(controller.delay(candidate, timeout_ms, delay_url)))
                    except Exception:
                        samples.append(None)
                successes = [sample for sample in samples if sample is not None]
                item["delay_samples_ms"] = samples
                item["successful_rounds"] = len(successes)
                item["median_delay_ms"] = statistics.median(successes) if successes else None
                item["jitter_ms"] = max(successes) - min(successes) if len(successes) > 1 else None
                if ipcheck_runner is not None and len(successes) == rounds:
                    try:
                        security = parse_ipcheck_output(ipcheck_runner(candidate))
                        item.update(security)
                        item["security_status"] = "PASS" if security["security_complete"] else "PARTIAL"
                    except Exception:
                        item["security_status"] = "FAIL"
                elif ipcheck_runner is not None:
                    item["security_status"] = "SKIPPED_UNSTABLE"
            except Exception:
                item.setdefault("successful_rounds", 0)
                item.setdefault("median_delay_ms", None)
                item.setdefault("jitter_ms", None)
                item["probe_status"] = "FAIL"
            results.append(item)
    finally:
        controller.switch(group, original)
        restored = controller.current(group) == original

    ranked = rank_results(results)
    recommendations = [
        item
        for item in ranked
        if item.get("successful_rounds") == item.get("rounds")
        and item.get("security_complete")
        and not item.get("compromised")
    ][:3]
    stability_shortlist = [
        item for item in ranked if item.get("successful_rounds") == item.get("rounds")
    ][:3]
    return {
        "group": group,
        "original": original,
        "original_restored": restored,
        "applied": False,
        "results": results,
        "stability_shortlist": stability_shortlist,
        "recommendations": recommendations,
    }


def _ipcheck_runner(command: str, timeout_seconds: int) -> Callable[[str], str]:
    argv = shlex.split(command, posix=os.name != "nt")
    if not argv:
        raise ValueError("ipcheck command is empty")

    def run(_: str) -> str:
        completed = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = (completed.stdout or "") + (completed.stderr or "")
        if completed.returncode != 0:
            raise RuntimeError("ipcheck failed")
        return output

    return run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--controller", default=DEFAULT_CONTROLLER)
    parser.add_argument("--group", required=True)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--timeout-ms", type=int, default=8000)
    parser.add_argument("--delay-url", default=DEFAULT_DELAY_URL)
    parser.add_argument("--ipcheck-command", default="ipcheck")
    parser.add_argument("--ipcheck-timeout-seconds", type=int, default=60)
    parser.add_argument("--settle-seconds", type=float, default=2.0)
    parser.add_argument("--latency-only", action="store_true")
    parser.add_argument("--confirm-external-ip-services", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.latency_only and not args.confirm_external_ip_services:
        print(
            "Refusing security checks without --confirm-external-ip-services; "
            "ipcheck sends the exit IP to third-party services.",
            file=sys.stderr,
        )
        return 2
    controller = ClashController(args.controller)
    runner = None if args.latency_only else _ipcheck_runner(
        args.ipcheck_command, args.ipcheck_timeout_seconds
    )
    report = probe_candidates(
        controller=controller,
        group=args.group,
        candidates=args.candidate,
        rounds=args.rounds,
        timeout_ms=args.timeout_ms,
        delay_url=args.delay_url,
        ipcheck_runner=runner,
        settle_seconds=args.settle_seconds,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["original_restored"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
