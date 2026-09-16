import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class NoBackgroundGuardTests(unittest.TestCase):
    def test_background_guard_installers_and_runtime_are_not_shipped(self):
        removed = (
            "scripts/network-guard.py",
            "scripts/install-windows-network-guard.ps1",
            "scripts/install-mac-network-guard.sh",
        )

        for relative_path in removed:
            self.assertFalse(
                (ROOT / relative_path).exists(),
                f"resident guard artifact must be removed: {relative_path}",
            )

    def test_skill_defines_on_demand_verification_without_notifications(self):
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        metadata = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")

        self.assertIn('version: "v2.5"', skill)
        self.assertIn("只在用户主动运行", skill)
        self.assertIn("不安装计划任务、开机启动项或 LaunchAgent", skill)
        self.assertIn("不会发送系统通知", skill)
        self.assertIn("一次性向导", readme)
        self.assertIn("按需复检", readme)

        forbidden = (
            "每 20 秒",
            "TestNotification",
            "可选安装日常自动守卫",
            "offer the opt-in daily guard",
            "自动提醒",
        )
        combined = "\n".join((skill, readme, metadata))
        for term in forbidden:
            self.assertNotIn(term, combined)

    def test_legacy_cleanup_scripts_remove_only_guard_artifacts(self):
        windows = (
            ROOT / "scripts" / "remove-legacy-windows-network-guard.ps1"
        ).read_text(encoding="utf-8")
        mac = (ROOT / "scripts" / "remove-legacy-mac-network-guard.sh").read_text(
            encoding="utf-8"
        )

        for term in (
            "FlClash Network Guard",
            "FlClash Network Guard.vbs",
            "flclash-network-setup\\network-guard",
        ):
            self.assertIn(term, windows)
        self.assertIn("com.marvx.flclash-network-guard.plist", mac)
        self.assertIn("flclash-network-setup/network-guard", mac)

        for script in (windows, mac):
            self.assertNotIn("ifconfig.co", script)
            self.assertNotIn("shared_preferences.json", script)

    def test_windows_audit_does_not_call_yaml_file_count_subscription_count(self):
        setup = (ROOT / "scripts" / "setup-windows.ps1").read_text(
            encoding="utf-8"
        )

        self.assertIn("Local profile YAML files", setup)
        self.assertIn("not the registered subscription count", setup)
        self.assertNotIn("Add-Result 'Profiles'", setup)


if __name__ == "__main__":
    unittest.main()
