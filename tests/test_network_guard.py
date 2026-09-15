import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "network-guard.py"
network_guard = None
if MODULE_PATH.exists():
    SPEC = importlib.util.spec_from_file_location("network_guard", MODULE_PATH)
    network_guard = importlib.util.module_from_spec(SPEC)
    assert SPEC.loader is not None
    SPEC.loader.exec_module(network_guard)


class NetworkGuardTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(network_guard, "scripts/network-guard.py is not implemented")

    def test_every_abnormal_notification_has_action_and_reason(self):
        cases = [
            {"proxy_listening": False, "tun_enabled": True},
            {"proxy_listening": True, "tun_enabled": False},
            {
                "proxy_listening": True,
                "tun_enabled": True,
                "proxy_exit": {"country": "US", "asn": "AS100"},
                "direct_ipv6": {"country": "CN", "asn": "AS200"},
            },
        ]

        alerts = [
            alert
            for observation in cases
            for alert in network_guard.evaluate_observation(observation)
        ]

        self.assertGreaterEqual(len(alerts), 3)
        for alert in alerts:
            self.assertTrue(alert["recommended_action"].strip())
            self.assertTrue(alert["reason"].strip())
            rendered = network_guard.render_notification(alert)
            self.assertIn("推荐操作：", rendered["body"])
            self.assertIn("原因：", rendered["body"])

    def test_ipv6_bypass_requires_a_real_mismatch(self):
        healthy = network_guard.evaluate_observation(
            {
                "proxy_listening": True,
                "tun_enabled": True,
                "proxy_exit": {"country": "US", "asn": "AS100"},
                "direct_ipv6": {"country": "US", "asn": "AS100"},
            }
        )
        no_ipv6 = network_guard.evaluate_observation(
            {
                "proxy_listening": True,
                "tun_enabled": True,
                "proxy_exit": {"country": "US", "asn": "AS100"},
                "direct_ipv6": None,
            }
        )

        self.assertNotIn("IPV6_BYPASS", {item["code"] for item in healthy})
        self.assertNotIn("IPV6_BYPASS", {item["code"] for item in no_ipv6})

    def test_alert_is_emitted_only_after_two_consecutive_observations(self):
        alert = network_guard.evaluate_observation(
            {"proxy_listening": False, "tun_enabled": True}
        )[0]
        state = {}

        state, first = network_guard.confirm_alerts(state, [alert], required=2)
        state, second = network_guard.confirm_alerts(state, [alert], required=2)
        state, recovered = network_guard.confirm_alerts(state, [], required=2)

        self.assertEqual(first, [])
        self.assertEqual([item["code"] for item in second], ["PROXY_DOWN"])
        self.assertEqual(recovered, [])
        self.assertEqual(state["consecutive"], {})

    def test_persisted_state_and_notifications_never_contain_raw_ip(self):
        raw_ip = "203.0.113.42"
        payload = {
            "proxy_exit": {
                "ip": raw_ip,
                "ip_decimal": 3405803786,
                "country": "US",
                "asn": "AS100",
            },
            "direct_ipv6": {"query": raw_ip, "country": "CN", "asn": "AS200"},
        }

        sanitized = network_guard.sanitize_for_storage(payload)
        alerts = network_guard.evaluate_observation(
            {
                "proxy_listening": True,
                "tun_enabled": True,
                **payload,
            }
        )
        serialized = json.dumps({"state": sanitized, "alerts": alerts}, ensure_ascii=False)

        self.assertNotIn(raw_ip, serialized)
        self.assertNotIn("3405803786", serialized)
        self.assertNotIn('"ip"', serialized.lower())
        self.assertNotIn('"query"', serialized.lower())

    def test_external_checks_require_consent_and_are_rate_limited(self):
        self.assertFalse(
            network_guard.should_run_external_check(
                consent=False,
                last_checked_at=0,
                now=10_000,
                interval_seconds=3600,
                network_changed=True,
            )
        )
        self.assertFalse(
            network_guard.should_run_external_check(
                consent=True,
                last_checked_at=9_000,
                now=10_000,
                interval_seconds=3600,
                network_changed=True,
            )
        )
        self.assertTrue(
            network_guard.should_run_external_check(
                consent=True,
                last_checked_at=0,
                now=10_000,
                interval_seconds=3600,
                network_changed=True,
            )
        )

    def test_windows_utf8_bom_config_is_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text('{"default_port": 54321}', encoding="utf-8-sig")

            parsed = network_guard._read_json(path, {})

        self.assertEqual(parsed["default_port"], 54321)

    def test_macos_notification_keeps_chinese_and_escapes_quotes(self):
        quoted = network_guard._applescript_quote('推荐“重启”\n原因：端口未监听')

        self.assertIn("推荐“重启”", quoted)
        self.assertIn("\\n", quoted)
        self.assertTrue(quoted.startswith('"') and quoted.endswith('"'))

    def test_installers_expose_lifecycle_controls(self):
        windows = (ROOT / "scripts" / "install-windows-network-guard.ps1").read_text(
            encoding="utf-8"
        )
        mac = (ROOT / "scripts" / "install-mac-network-guard.sh").read_text(
            encoding="utf-8"
        )

        for term in ("Install", "Uninstall", "Pause", "Resume", "Status", "CheckNow"):
            self.assertIn(term, windows)
        self.assertIn("Register-ScheduledTask", windows)
        for term in ("install", "uninstall", "pause", "resume", "status", "check-now"):
            self.assertIn(term, mac)
        self.assertIn("LaunchAgents", mac)
        self.assertIn("osascript", mac)

    def test_skill_explains_opt_in_guard_and_actionable_notifications(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn('version: "v2.4"', skill)
        for term in (
            "日常自动守卫",
            "正常状态保持静默",
            "推荐操作",
            "简要原因",
            "连续两次",
            "不会自动关闭 IPv6",
            "单独授权",
        ):
            self.assertIn(term, skill)
        self.assertIn("日常自动守卫", readme)
        self.assertIn("暂停、恢复、立即检查和卸载", readme)


if __name__ == "__main__":
    unittest.main()
