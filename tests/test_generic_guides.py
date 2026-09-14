import unittest
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


class GenericGuideTests(unittest.TestCase):
    def test_shareable_configuration_guide_exists(self):
        text = (ROOT / "references" / "optimization-config-guide.md").read_text(encoding="utf-8")
        for term in (
            "mixed-port", "fake-ip-range", "default-nameserver", "nameserver-policy",
            "fake-ip-filter", "自动识别节点域名", "dry-run", "受保护尾部",
        ):
            self.assertIn(term, text)

    def test_platform_guides_are_substantive_and_sanitized(self):
        windows = (ROOT / "references" / "windows-guide-2026-07.md").read_text(encoding="utf-8")
        mac = (ROOT / "references" / "mac-intel-guide-2026-09.md").read_text(encoding="utf-8")
        self.assertGreaterEqual(len(windows.splitlines()), 45)
        self.assertGreaterEqual(len(mac.splitlines()), 55)
        combined = windows + mac + (ROOT / "references" / "optimization-config-guide.md").read_text(encoding="utf-8")
        fixed_policy_domains = re.findall(r"domain:([a-z0-9][a-z0-9.-]+)", combined.lower())
        self.assertEqual(fixed_policy_domains, [])

    def test_reference_folder_only_contains_curated_guides(self):
        names = {path.name for path in (ROOT / "references").glob("*.md")}
        self.assertEqual(
            names,
            {
                "beginner-guide.md",
                "mac-intel-guide-2026-09.md",
                "optimization-config-guide.md",
                "privacy-and-rollback.md",
                "windows-guide-2026-07.md",
            },
        )


if __name__ == "__main__":
    unittest.main()
