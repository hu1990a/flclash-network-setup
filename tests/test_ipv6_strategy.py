import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS_TOOL = ROOT / "scripts" / "manage-windows-ipv6.ps1"
WINDOWS_SETUP = ROOT / "scripts" / "setup-windows.ps1"
IS_WINDOWS = sys.platform == "win32"
SKIP_REASON = "Windows-only: drives powershell.exe"


class IPv6StrategyTests(unittest.TestCase):
    def run_windows_plan(self, strategy: str):
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(WINDOWS_TOOL),
                "-Mode",
                "Plan",
                "-Strategy",
                strategy,
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return json.loads(result.stdout)

    @unittest.skipUnless(IS_WINDOWS, SKIP_REASON)
    def test_windows_default_plan_prefers_ipv4_and_keeps_ipv6_bound(self):
        plan = self.run_windows_plan("PreferIPv4")

        self.assertEqual(plan["registryValue"], 32)
        self.assertTrue(plan["requiresRestart"])
        self.assertFalse(plan["disableAdapterBindings"])

    @unittest.skipUnless(IS_WINDOWS, SKIP_REASON)
    def test_windows_strict_plan_is_explicit_and_scoped_to_active_adapters(self):
        plan = self.run_windows_plan("StrictDisable")

        self.assertTrue(plan["disableAdapterBindings"])
        self.assertEqual(plan["adapterScope"], "selected active physical adapters")
        self.assertTrue(plan["requiresExplicitSelection"])

    def test_macos_default_keeps_automatic_ipv6(self):
        script = (ROOT / "scripts" / "setup-mac.sh").read_text(encoding="utf-8")

        self.assertIn('IPV6_MODE="${FLCLASH_IPV6_MODE:-keep}"', script)
        self.assertIn('strict-disable', script)
        self.assertNotIn('read -r -p "Network service to disable IPv6 on', script)

    @unittest.skipUnless(IS_WINDOWS, SKIP_REASON)
    def test_windows_audit_does_not_forward_an_empty_adapter_argument(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            appdata = Path(temp_dir) / "appdata"
            clash = appdata / "com.follow" / "clash"
            profiles = clash / "profiles"
            profiles.mkdir(parents=True)
            (profiles / "test.yaml").write_text("proxies:\n", encoding="utf-8")
            inner = {
                "currentProfileId": "test",
                "patchClashConfig": {"mixed-port": 7890},
                "vpnProps": {"enable": True},
                "networkProps": {"systemProxy": True},
            }
            (clash / "shared_preferences.json").write_text(
                json.dumps({"flutter.config": json.dumps(inner)}), encoding="utf-8"
            )
            env = os.environ.copy()
            env["APPDATA"] = str(appdata)

            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(WINDOWS_SETUP),
                    "-Mode",
                    "Audit",
                ],
                env=env,
                text=True,
                capture_output=True,
                timeout=20,
            )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("Missing an argument for parameter 'AdapterName'", result.stdout + result.stderr)

    def test_windows_verify_does_not_persist_user_path(self):
        script = WINDOWS_SETUP.read_text(encoding="utf-8")

        self.assertIn("function Ensure-PythonUserScriptsPath([switch]$PersistUserPath)", script)
        self.assertIn("if($PersistUserPath -and", script)
        self.assertIn("Ensure-PythonUserScriptsPath -PersistUserPath", script)


if __name__ == "__main__":
    unittest.main()
