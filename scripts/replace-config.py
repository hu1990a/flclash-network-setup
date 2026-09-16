#!/usr/bin/env python3
"""Safely optimize one FlClash subscription profile.

Only content before the top-level ``proxies:`` key is replaced. Node domains
are detected at runtime and resolved via DoH (encryption is the default, no
user-maintained sensitive list); the fixed CN whitelist resolves via plaintext
domestic DNS for speed only. Credentials, proxy names, subscription URLs,
server addresses, and absolute user paths are never printed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import ipaddress
import json
import re
import shutil
from pathlib import Path


CN_DOMAINS = [
    "weixin.qq.com", "qq.com", "tencent.com", "wechat.com", "weixinbridge.com",
    "qpic.cn", "qlogo.cn", "qqmail.com", "tenpay.com", "taobao.com", "tmall.com",
    "alipay.com", "baidu.com", "bilibili.com", "jd.com", "163.com", "126.com",
    "meituan.com", "douyin.com", "toutiao.com",
]
DOH_SERVERS = [
    "https://cloudflare-dns.com/dns-query",
    "https://dns.google/dns-query",
    "https://dns.alidns.com/dns-query",
    "https://doh.pub/dns-query",
]
FAKE_IP_FILTER = [
    "*.lan", "*.localdomain", "*.example", "*.invalid", "*.localhost", "*.test",
    "*.local", "*.home.arpa", "time.*.com", "time.*.gov", "time.*.edu.cn",
    "time.*.apple.com", "time1.*.com", "time2.*.com", "time3.*.com",
    "time4.*.com", "time5.*.com", "time6.*.com", "time7.*.com",
    "ntp.*.com", "ntp1.*.com", "ntp2.*.com", "ntp3.*.com",
    "ntp4.*.com", "ntp5.*.com", "ntp6.*.com", "ntp7.*.com",
    "*.time.edu.cn", "*.ntp.org.cn", "+.pool.ntp.org",
    "time1.cloud.tencent.com", "music.163.com", "*.music.163.com", "*.126.net",
    "musicapi.taihe.com", "music.taihe.com", "songsearch.kugou.com",
    "trackercdn.kugou.com", "*.kuwo.cn", "api-jooxtt.sanook.com",
    "api.joox.com", "joox.com", "y.qq.com", "*.y.qq.com",
    "streamoc.music.tc.qq.com", "mobileoc.music.tc.qq.com",
    "isure.stream.qqmusic.qq.com", "dl.stream.qqmusic.qq.com",
    "aqqmusic.tc.qq.com", "amobile.music.tc.qq.com", "*.xiami.com",
    "*.music.migu.cn", "music.migu.cn", "+.msftconnecttest.com", "+.msftncsi.com",
    "msftconnecttest.com", "msftncsi.com", "localhost.ptlogin2.qq.com",
    "localhost.sec.qq.com", "+.srv.nintendo.net", "+.stun.playstation.net",
    "xbox.*.microsoft.com", "xnotify.xboxlive.com", "+.ipv6.microsoft.com",
    "+.battlenet.com.cn",
    "+.wotgame.cn", "+.wggames.cn", "+.wowsgame.cn", "+.wargaming.net",
    "proxy.golang.org", "stun.*.*", "stun.*.*.*", "+.stun.*.*",
    "+.stun.*.*.*", "+.stun.*.*.*.*", "heartbeat.belkin.com", "*.linksys.com",
    "*.linksyssmartwifi.com", "*.router.asus.com", "mesu.apple.com",
    "swscan.apple.com", "swquery.apple.com", "swdownload.apple.com",
    "swcdn.apple.com", "swdist.apple.com", "lens.l.google.com",
    "stun.l.google.com", "*.square-enix.com", "*.finalfantasyxiv.com",
    "*.ffxiv.com", "*.ff14.sdo.com", "ff.dorado.sdo.com", "*.mcdn.bilivideo.cn",
    "+.media.dssott.com", "+.pvp.net",
]


def split_profile(text: str) -> tuple[str, str]:
    match = re.search(r"(?m)^proxies:\s*$", text)
    if not match:
        raise ValueError("no top-level proxies key found")
    return text[: match.start()], text[match.start() :].lstrip("\r\n")


def extract_node_domains(tail: str) -> list[str]:
    proxy_block = re.split(r"(?m)^proxy-groups:\s*$", tail, maxsplit=1)[0]
    candidates = re.findall(r"\bserver:\s*['\"]?([^,'\"}\]\s]+)", proxy_block)
    domains: set[str] = set()
    for candidate in candidates:
        value = candidate.strip().rstrip(".").lower()
        try:
            ipaddress.ip_address(value.strip("[]"))
            continue
        except ValueError:
            pass
        if re.fullmatch(r"[a-z0-9._-]+", value) and "." in value:
            domains.add(value)
    return sorted(domains)


def yaml_list(values: list[str], indent: int) -> str:
    pad = " " * indent
    return "\n".join(f"{pad}- {value}" for value in values)


def build_header(node_domains: list[str], port: int) -> str:
    cn_policy = sorted(set(CN_DOMAINS))
    doh_policy = sorted(set(node_domains))
    lines = [
        f"mixed-port: {port}", "ipv6: false", "udp: true", "allow-lan: false",
        "bind-address: '*'", "mode: rule", "log-level: info", "unified-delay: true",
        "experimental:", "  ignore-resolve-fail: true", "dns:", "  enable: true",
        "  listen: '127.0.0.1:1053'", "  ipv6: false", "  use-hosts: true",
        "  enhanced-mode: fake-ip", "  fake-ip-range: 198.18.0.1/16",
        "  default-nameserver:", "    - 223.5.5.5", "    - 119.29.29.29",
        "    - 1.1.1.1", "  nameserver:", "    - 1.1.1.1", "    - 8.8.8.8",
        "    - 223.5.5.5", "  fallback:", "    - 8.8.8.8", "    - tls://1.1.1.1",
        "  fallback-filter:", "    geoip: true", "    geoip-code: CN", "    ipcidr:",
        "      - 240.0.0.0/4", "      - 0.0.0.0/32", "      - 127.0.0.1/32",
        "  nameserver-policy:",
    ]
    # Encryption is the default: subscription transit domains resolve via DoH
    # (auto-extracted, follows the subscription, no user-maintained list).
    for domain in doh_policy:
        lines.extend([f"    'domain:{domain}':", yaml_list(DOH_SERVERS, 6)])
    # Plaintext domestic DNS is the exception: fixed CN whitelist, speed only.
    for domain in cn_policy:
        lines.extend([f"    'domain:{domain}':", "      - 119.29.29.29", "      - 223.5.5.5"])
    filters = ", ".join("'" + item + "'" for item in FAKE_IP_FILTER)
    lines.append("  fake-ip-filter: [" + filters + "]")
    return "\n".join(lines) + "\n\n"


def safe_counts(tail: str) -> dict[str, int]:
    proxy_block = re.split(r"(?m)^proxy-groups:\s*$", tail, maxsplit=1)[0]
    group_parts = re.split(r"(?m)^proxy-groups:\s*$", tail, maxsplit=1)
    group_block = re.split(r"(?m)^rules:\s*$", group_parts[1], maxsplit=1)[0] if len(group_parts) > 1 else ""
    rules_parts = re.split(r"(?m)^rules:\s*$", tail, maxsplit=1)
    rules_block = rules_parts[1] if len(rules_parts) > 1 else ""
    return {
        "proxy_entries": len(re.findall(r"(?m)^\s*-\s+(?:\{|name:)", proxy_block)),
        "group_entries": len(re.findall(r"(?m)^\s*-\s+(?:\{|name:)", group_block)),
        "rule_entries": len(re.findall(r"(?m)^\s*-\s+", rules_block)),
    }


def optimize(args: argparse.Namespace) -> dict[str, object]:
    path = Path(args.profile).expanduser().resolve()
    text = path.read_text(encoding="utf-8-sig")
    _, tail = split_profile(text)
    detected = [] if args.no_auto_node_domains else extract_node_domains(tail)
    node_domains = sorted(set(detected + args.node_domain))
    if not node_domains:
        raise ValueError("no node domains detected; pass --node-domain explicitly")
    new_text = build_header(node_domains, args.port) + tail.rstrip() + "\n"
    tail_hash = hashlib.sha256(tail.encode()).hexdigest()
    result: dict[str, object] = {
        "file": path.name,
        "changed": new_text != text,
        "dry_run": args.dry_run,
        "node_domain_count": len(node_domains),
        "tail_sha256": tail_hash,
        **safe_counts(tail),
    }
    if args.dry_run or new_text == text:
        return result
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = path.with_name(path.name + ".bak." + stamp)
    shutil.copy2(path, backup)
    path.write_text(new_text, encoding="utf-8")
    _, written_tail = split_profile(path.read_text(encoding="utf-8"))
    if hashlib.sha256(written_tail.encode()).hexdigest() != tail_hash:
        shutil.copy2(backup, path)
        raise RuntimeError("protected profile tail changed; original restored")
    result["backup"] = backup.name
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Optimize a FlClash profile without exposing secrets.")
    parser.add_argument("profile", help="profile YAML path")
    parser.add_argument("--port", type=int, default=7890)
    parser.add_argument("--node-domain", action="append", default=[])
    parser.add_argument("--no-auto-node-domains", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> int:
    try:
        print(json.dumps(optimize(parse_args()), ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
