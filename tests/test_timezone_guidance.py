import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TimeZoneGuidanceTests(unittest.TestCase):
    def test_skill_requires_two_explicit_beginner_choices(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("选项 1：固定比北京时间慢 12 小时", text)
        self.assertIn("选项 2（推荐）：与当前或推荐代理出口一致", text)
        self.assertIn("用户选择前不得写入", text)

    def test_beginner_guide_explains_both_tradeoffs(self):
        text = (ROOT / "references" / "beginner-guide.md").read_text(encoding="utf-8")
        self.assertIn("方便人类日常换算", text)
        self.assertIn("减少出口位置与 CLI 时区冲突", text)
        self.assertIn("夏令时", text)

    def test_platform_prompts_support_proxy_timezone_choice(self):
        windows = (ROOT / "scripts" / "setup-windows.ps1").read_text(encoding="utf-8")
        mac = (ROOT / "scripts" / "setup-mac.sh").read_text(encoding="utf-8")
        self.assertIn("[string]$ProxyTimeZone", windows)
        self.assertIn("Choice 2 is recommended", windows)
        self.assertIn("FLCLASH_PROXY_TIMEZONE", mac)
        self.assertIn("Choice 2 is recommended", mac)


if __name__ == "__main__":
    unittest.main()
