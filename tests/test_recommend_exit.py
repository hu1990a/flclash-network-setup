import importlib.util
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parents[1] / "scripts" / "recommend-exit.py"
SPEC = importlib.util.spec_from_file_location("recommend_exit", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)

SAMPLE = """proxies:
  - {name: Puerto Rico 01, server: hidden.example, password: SECRET}
  - {name: New York 01, server: hidden.example, password: SECRET}
  - {name: Tokyo 01, server: hidden.example, password: SECRET}
proxy-groups:
  - {name: auto, type: select, proxies: []}
rules:
  - MATCH,auto
"""


class RecommendExitTests(unittest.TestCase):
    def test_exact_timezone_is_ranked_first_without_node_names(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(SAMPLE, encoding="utf-8")
            result = MODULE.analyze([str(path)], "America/Puerto_Rico")
            self.assertEqual(result["recommended_region"], "Puerto Rico")
            self.assertEqual(result["candidates"][0]["match_type"], "exact_timezone")
            serialized = str(result)
            self.assertNotIn("Puerto Rico 01", serialized)
            self.assertNotIn("SECRET", serialized)
            self.assertNotIn(str(path.parent), serialized)

    def test_new_york_is_current_offset_only_and_warns_about_dst(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(SAMPLE.replace("Puerto Rico 01", "Unknown 01"), encoding="utf-8")
            result = MODULE.analyze([str(path)], "America/Puerto_Rico")
            east = next(x for x in result["candidates"] if x["region"] == "US East")
            self.assertTrue(east["observes_dst"])
    def test_does_not_recommend_region_more_than_three_hours_away(self):
        distant = """proxies:
  - {name: Tokyo 01, server: hidden.example, password: SECRET}
proxy-groups: []
rules: []
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(distant, encoding="utf-8")
            result = MODULE.analyze([str(path)], "America/Puerto_Rico")
            self.assertIsNone(result["recommended_region"])
            self.assertIn("no suitable timezone match", result["recommendation_basis"])


    def test_country_only_nodes_are_reported_for_active_probe(self):
        sample = """proxies:
  - {name: 美国 01, server: hidden.example, password: SECRET}
proxy-groups: []
rules: []
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(sample, encoding="utf-8")
            result = MODULE.analyze([str(path)], "America/Puerto_Rico")
            self.assertEqual(
                result.get("probe_required"),
                [{"label_scope": "country_only", "country": "United States", "city": None, "candidate_count": 1}],
            )
            self.assertIsNone(result["recommended_region"])

if __name__ == "__main__":
    unittest.main()