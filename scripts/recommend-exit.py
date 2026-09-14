#!/usr/bin/env python3
"""Recommend proxy exit regions for a target CLI timezone without exposing nodes."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import Counter
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

REGIONS = [
    ("Puerto Rico", "America/Puerto_Rico", ["puerto rico", "波多黎各", "pr-"]),
    ("US East", "America/New_York", ["new york", "纽约", "us east", "us-east", "美东"]),
    ("US West", "America/Los_Angeles", ["los angeles", "洛杉矶", "san jose", "硅谷", "us west", "us-west", "美西"]),
    ("Japan", "Asia/Tokyo", ["tokyo", "东京", "日本", "jp-"]),
    ("Singapore", "Asia/Singapore", ["singapore", "新加坡", "sg-"]),
    ("Hong Kong", "Asia/Hong_Kong", ["hong kong", "香港", "hk-"]),
    ("Taiwan", "Asia/Taipei", ["taiwan", "台湾", "台北", "tw-"]),
    ("United Kingdom", "Europe/London", ["london", "伦敦", "英国", "uk-"]),
    ("Germany", "Europe/Berlin", ["berlin", "法兰克福", "德国", "de-"]),
    ("Australia", "Australia/Sydney", ["sydney", "悉尼", "澳大利亚", "au-"]),
]
COUNTRY_ONLY_PATTERNS = [
    ("United States", re.compile(r"美国|united states|\busa\b|(?:^|[^a-z])us(?:[^a-z]|$)", re.IGNORECASE)),
]

STATIC_OFFSETS = {
    "America/Puerto_Rico": -240, "America/New_York": -240,
    "America/Los_Angeles": -420, "Asia/Tokyo": 540,
    "Asia/Singapore": 480, "Asia/Hong_Kong": 480, "Asia/Taipei": 480,
    "Europe/London": 60, "Europe/Berlin": 120, "Australia/Sydney": 600,
}


def proxy_names(text: str) -> list[str]:
    block = re.split(r"(?m)^proxy-groups:\s*$", text, maxsplit=1)[0]
    names = re.findall(r"(?m)^\s*-\s*name:\s*([^\r\n]+)$", block)
    names += re.findall(r"\{\s*name:\s*([^,}\r\n]+)", block)
    return [n.strip().strip("'\"") for n in names]


def classify(name: str) -> tuple[str, str] | None:
    value = name.casefold().replace("_", " ")
    for region, timezone, patterns in REGIONS:
        if any(pattern.casefold() in value for pattern in patterns):
            return region, timezone
    return None


def offset_minutes(timezone: str, when: dt.datetime) -> int:
    try:
        delta = when.astimezone(ZoneInfo(timezone)).utcoffset()
        if delta is not None:
            return int(delta.total_seconds() // 60)
    except ZoneInfoNotFoundError:
        pass
    if timezone in STATIC_OFFSETS:
        return STATIC_OFFSETS[timezone]
    raise ValueError(f"timezone data unavailable for {timezone}")


def analyze(paths: list[str], target_timezone: str) -> dict[str, object]:
    now = dt.datetime.now(dt.timezone.utc)
    target_offset = offset_minutes(target_timezone, now)
    counts: Counter[tuple[str, str]] = Counter()
    probe_counts: Counter[str] = Counter()
    unknown = 0
    files = []
    for raw in paths:
        path = Path(raw).expanduser().resolve()
        names = proxy_names(path.read_text(encoding="utf-8-sig"))
        files.append({"file": path.name, "proxy_names_scanned": len(names)})
        for name in names:
            result = classify(name)
            if result is None:
                normalized = name.casefold().replace("_", " ")
                country = next(
                    (country for country, pattern in COUNTRY_ONLY_PATTERNS if pattern.search(normalized)),
                    None,
                )
                if country:
                    probe_counts[country] += 1
                else:
                    unknown += 1
            else:
                counts[result] += 1
    candidates = []
    for (region, timezone), count in counts.items():
        current_offset = offset_minutes(timezone, now)
        jan = offset_minutes(timezone, dt.datetime(now.year, 1, 15, tzinfo=dt.timezone.utc))
        jul = offset_minutes(timezone, dt.datetime(now.year, 7, 15, tzinfo=dt.timezone.utc))
        gap = abs(current_offset - target_offset)
        match = "exact_timezone" if timezone == target_timezone else "current_utc_offset" if gap == 0 else "nearest_offset"
        candidates.append({
            "region": region, "timezone": timezone, "candidate_count": count,
            "utc_offset_minutes_now": current_offset, "offset_gap_minutes": gap,
            "match_type": match, "observes_dst": jan != jul,
        })
    order = {"exact_timezone": 0, "current_utc_offset": 1, "nearest_offset": 2}
    candidates.sort(key=lambda item: (order[item["match_type"]], item["offset_gap_minutes"], -item["candidate_count"], item["region"]))
    best = candidates[0] if candidates else None
    suitable = bool(
        best
        and (
            best["match_type"] in {"exact_timezone", "current_utc_offset"}
            or best["offset_gap_minutes"] <= 180
        )
    )
    return {
        "target_cli_timezone": target_timezone,
        "target_utc_offset_minutes_now": target_offset,
        "profiles": files,
        "unknown_region_count": unknown,
        "probe_required": [
            {
                "label_scope": "country_only",
                "country": country,
                "city": None,
                "candidate_count": count,
            }
            for country, count in sorted(probe_counts.items())
        ],
        "recommended_region": best["region"] if suitable else None,
        "recommendation_basis": (
            "timezone match only; use FlClash delay test and reject TIMEOUT before switching"
            if suitable
            else "no suitable timezone match; keep the current exit or choose a CLI timezone that matches a verified exit"
        ),
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("profiles", nargs="+")
    parser.add_argument("--target-timezone", default="America/Puerto_Rico")
    args = parser.parse_args()
    print(json.dumps(analyze(args.profiles, args.target_timezone), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())