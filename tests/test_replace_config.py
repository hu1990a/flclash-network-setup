import argparse
import importlib.util
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path


SCRIPT = Path(__file__).parents[1] / "scripts" / "replace-config.py"
SPEC = importlib.util.spec_from_file_location("replace_config", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


SAMPLE = """mixed-port: 9999
dns:
  ipv6: true
proxies:
  - {name: REDACT_ME, server: node-1.example-provider.test, port: 443, password: SECRET_VALUE}
  - name: second
    server: node-2.example-provider.test
    port: 443
proxy-groups:
  - {name: auto, type: select, proxies: [REDACT_ME]}
rules:
  - MATCH,auto
"""


class ReplaceConfigTests(unittest.TestCase):
    def args(self, path: Path, dry_run: bool = False):
        return argparse.Namespace(
            profile=str(path), port=7890, node_domain=[],
            no_auto_node_domains=False, dry_run=dry_run,
        )

    def test_detects_node_domains_without_credentials(self):
        _, tail = MODULE.split_profile(SAMPLE)
        self.assertEqual(
            MODULE.extract_node_domains(tail),
            ["node-1.example-provider.test", "node-2.example-provider.test"],
        )

    def test_write_preserves_protected_tail_and_creates_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(SAMPLE, encoding="utf-8")
            _, original_tail = MODULE.split_profile(SAMPLE)
            result = MODULE.optimize(self.args(path))
            _, new_tail = MODULE.split_profile(path.read_text(encoding="utf-8"))
            self.assertEqual(original_tail, new_tail)
            self.assertTrue((path.parent / result["backup"]).exists())
            written = path.read_text(encoding="utf-8")
            self.assertIn("ipv6: false", written)
            self.assertIn("fake-ip-range: 198.18.0.1/16", written)
            self.assertIn("domain:node-1.example-provider.test", written)

    def test_cli_output_is_sanitized(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.yaml"
            path.write_text(SAMPLE, encoding="utf-8")
            stream = StringIO()
            with redirect_stdout(stream):
                print(json.dumps(MODULE.optimize(self.args(path, dry_run=True))))
            output = stream.getvalue()
            self.assertNotIn("SECRET_VALUE", output)
            self.assertNotIn("REDACT_ME", output)
            self.assertNotIn(str(path.parent), output)


    def test_many_node_domains_produce_valid_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML unavailable")
        domains = [f"node-{index}.example-provider.test" for index in range(80)]
        document = MODULE.build_header(domains, 7890) + "proxies: []\nproxy-groups: []\nrules: []\n"
        parsed = yaml.safe_load(document)
        self.assertEqual(parsed["dns"]["fake-ip-range"], "198.18.0.1/16")
        self.assertGreaterEqual(len(parsed["dns"]["nameserver-policy"]), 80)

    def test_full_compatibility_filter_set_is_present(self):
        restored = {
            "time1.*.com", "time7.*.com", "ntp1.*.com", "ntp7.*.com",
            "*.time.edu.cn", "api-jooxtt.sanook.com", "api.joox.com",
            "joox.com", "streamoc.music.tc.qq.com", "mobileoc.music.tc.qq.com",
            "isure.stream.qqmusic.qq.com", "dl.stream.qqmusic.qq.com",
            "aqqmusic.tc.qq.com", "amobile.music.tc.qq.com", "*.xiami.com",
            "+.ipv6.microsoft.com",
        }
        self.assertTrue(restored.issubset(set(MODULE.FAKE_IP_FILTER)))
        self.assertGreaterEqual(len(MODULE.FAKE_IP_FILTER), 95)
        self.assertEqual(len(MODULE.FAKE_IP_FILTER), len(set(MODULE.FAKE_IP_FILTER)))

    def test_generic_header_omits_legacy_frontend_and_fixed_hosts(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML unavailable")
        parsed = yaml.safe_load(MODULE.build_header(["node.example"], 7890))
        self.assertNotIn("hosts", parsed)
        self.assertFalse(any(key.startswith("cfw-") for key in parsed))

    def test_node_domains_resolve_via_doh_and_cn_whitelist_via_plaintext(self):
        """Encryption is the default: subscription transit domains go to the
        DoH group; the fixed CN whitelist goes to plaintext domestic DNS."""
        header = MODULE.build_header(["node.example"], 7890)
        node_section = header.split("'domain:node.example':")[1].split("'domain:")[0]
        self.assertIn("https://dns.alidns.com/dns-query", node_section)
        self.assertIn("https://doh.pub/dns-query", node_section)
        self.assertIn("https://cloudflare-dns.com/dns-query", node_section)
        cn_section = header.split("'domain:baidu.com':")[1].split("'domain:")[0]
        self.assertIn("119.29.29.29", cn_section)
        self.assertNotIn("https://", cn_section)
        # No user-maintained sensitive list: DoH entries only come from
        # auto-extracted node domains.
        self.assertNotIn("sensitive", header)


if __name__ == "__main__":
    unittest.main()
