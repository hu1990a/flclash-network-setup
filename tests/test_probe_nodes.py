import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "probe-nodes.py"
probe_nodes = None
if MODULE_PATH.exists():
    SPEC = importlib.util.spec_from_file_location("probe_nodes", MODULE_PATH)
    probe_nodes = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(probe_nodes)


def ipcheck_output(risk=0, abuse=None, city="San Jose", provider="xTom"):
    abuse_text = "未收录  低风险" if abuse is None else f"举报 {abuse} 次"
    recent_text = "" if abuse is None else "║                      │ 最近举报 2026-04-08"
    return f"""
    ║ 出口 IP              │ 203.0.113.42
    ║ 城市                 │ {city}
    ║ 运营商               │ {provider}
    ║ 所处时区             │ America/Los_Angeles  (UTC-07:00)
    ║ 机房 / 住宅          │ 机房 IP
    ║ IP 风险查询          │ {risk}/100 低风险  类型 Business
    ║ 垃圾滥用记录         │ {abuse_text}
    {recent_text}
    """


class FakeController:
    def __init__(self, original, delays):
        self.selected = original
        self.delays = delays
        self.switches = []
        self.delay_index = {}

    def current(self, group):
        return self.selected

    def switch(self, group, candidate):
        self.selected = candidate
        self.switches.append(candidate)

    def delay(self, candidate, timeout_ms, delay_url):
        index = self.delay_index.get(candidate, 0)
        self.delay_index[candidate] = index + 1
        value = self.delays[candidate][index]
        if value is None:
            raise TimeoutError(candidate)
        return value


class ProbeNodeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(probe_nodes, "scripts/probe-nodes.py is not implemented")

    def test_ipcheck_parser_extracts_security_without_retaining_ip(self):
        parsed = probe_nodes.parse_ipcheck_output(ipcheck_output(risk=12, abuse=3))

        self.assertEqual(parsed["risk_score"], 12)
        self.assertEqual(parsed["abuse_reports"], 3)
        self.assertEqual(parsed["timezone"], "America/Los_Angeles")
        self.assertEqual(parsed["city"], "San Jose")
        self.assertEqual(parsed["last_reported"], "2026-04-08")
        self.assertNotIn("203.0.113.42", json.dumps(parsed, ensure_ascii=False))

    def test_ranking_prefers_complete_stability_before_lower_latency(self):
        results = [
            {
                "candidate": "fast-but-flaky",
                "successful_rounds": 2,
                "rounds": 3,
                "median_delay_ms": 120,
                "jitter_ms": 5,
                "risk_score": 0,
                "abuse_reports": 0,
                "security_complete": True,
                "compromised": False,
            },
            {
                "candidate": "stable-clean",
                "successful_rounds": 3,
                "rounds": 3,
                "median_delay_ms": 210,
                "jitter_ms": 12,
                "risk_score": 0,
                "abuse_reports": 0,
                "security_complete": True,
                "compromised": False,
            },
            {
                "candidate": "stable-dirty",
                "successful_rounds": 3,
                "rounds": 3,
                "median_delay_ms": 180,
                "jitter_ms": 8,
                "risk_score": 83,
                "abuse_reports": 9,
                "security_complete": True,
                "compromised": True,
            },
        ]

        ranked = probe_nodes.rank_results(results)

        self.assertEqual(ranked[0]["candidate"], "stable-clean")
        self.assertEqual(ranked[-1]["candidate"], "fast-but-flaky")

    def test_ranking_prefers_older_abuse_record_when_other_metrics_match(self):
        common = {
            "successful_rounds": 3,
            "rounds": 3,
            "median_delay_ms": 200,
            "jitter_ms": 10,
            "risk_score": 20,
            "abuse_reports": 2,
            "security_complete": True,
            "compromised": False,
        }
        ranked = probe_nodes.rank_results(
            [
                {**common, "candidate": "a-recent", "last_reported": "2026-09-15"},
                {**common, "candidate": "z-older", "last_reported": "2026-04-08"},
            ]
        )

        self.assertEqual(ranked[0]["candidate"], "z-older")

    def test_probe_restores_original_and_only_recommends(self):
        controller = FakeController(
            "original",
            {"clean": [210, 200, 205], "dirty": [180, 185, 182]},
        )

        def runner(candidate):
            return ipcheck_output(risk=0 if candidate == "clean" else 83, abuse=None if candidate == "clean" else 9)

        report = probe_nodes.probe_candidates(
            controller=controller,
            group="Proxy",
            candidates=["clean", "dirty"],
            rounds=3,
            timeout_ms=8000,
            delay_url="http://example.test/generate_204",
            ipcheck_runner=runner,
        )

        self.assertEqual(controller.selected, "original")
        self.assertEqual(controller.switches[-1], "original")
        self.assertEqual(report["recommendations"][0]["candidate"], "clean")
        self.assertFalse(report["applied"])

    def test_probe_restores_original_after_security_check_error(self):
        controller = FakeController("original", {"broken": [200, 200, 200]})

        def runner(candidate):
            raise RuntimeError("provider unavailable")

        report = probe_nodes.probe_candidates(
            controller=controller,
            group="Proxy",
            candidates=["broken"],
            rounds=3,
            timeout_ms=8000,
            delay_url="http://example.test/generate_204",
            ipcheck_runner=runner,
        )

        self.assertEqual(controller.selected, "original")
        self.assertEqual(report["results"][0]["security_status"], "FAIL")
        self.assertEqual(report["recommendations"], [])

    def test_unstable_candidate_does_not_send_ip_to_security_services(self):
        controller = FakeController("original", {"flaky": [150, None, 160]})
        checked = []

        def runner(candidate):
            checked.append(candidate)
            return ipcheck_output()

        report = probe_nodes.probe_candidates(
            controller=controller,
            group="Proxy",
            candidates=["flaky"],
            rounds=3,
            timeout_ms=8000,
            delay_url="http://example.test/generate_204",
            ipcheck_runner=runner,
        )

        self.assertEqual(checked, [])
        self.assertEqual(report["results"][0]["security_status"], "SKIPPED_UNSTABLE")

    def test_probe_waits_for_route_to_settle_after_switch(self):
        controller = FakeController("original", {"candidate": [200, 200]})
        waits = []

        probe_nodes.probe_candidates(
            controller=controller,
            group="Proxy",
            candidates=["candidate"],
            rounds=2,
            timeout_ms=8000,
            delay_url="http://example.test/generate_204",
            ipcheck_runner=lambda _: ipcheck_output(),
            settle_seconds=2.0,
            sleeper=waits.append,
        )

        self.assertEqual(waits, [2.0])


if __name__ == "__main__":
    unittest.main()
