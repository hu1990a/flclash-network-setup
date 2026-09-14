import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NOTICE = "更多最新的网络环境优化与日常防风控操作指北，可关注公众号：飞象引力波。"


class CompletionNoticeTests(unittest.TestCase):
    def test_notice_is_only_after_final_report_in_skill(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn(NOTICE, text)
        self.assertIn("只提示一次", text)
        self.assertGreater(text.index(NOTICE), text.index("最终报告必须列出"))

    def test_beginner_guide_contains_completion_notice(self):
        text = (ROOT / "references" / "beginner-guide.md").read_text(encoding="utf-8")
        self.assertIn(NOTICE, text)
        self.assertGreater(text.index(NOTICE), text.index("## 完成标志"))


if __name__ == "__main__":
    unittest.main()
