import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "scripts" / "install-windows-proxy-guard.ps1"
IS_WINDOWS = sys.platform == "win32"
SKIP_REASON = "Windows-only: drives powershell.exe"


def ps_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


@unittest.skipUnless(IS_WINDOWS, SKIP_REASON)
class WindowsProxyGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.profile = self.root / "profile.ps1"
        self.appdata = self.root / "appdata"
        self.clash_root = self.appdata / "com.follow" / "clash"
        self.clash_root.mkdir(parents=True)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()

    def tearDown(self):
        self.temp_dir.cleanup()

    def write_flclash_state(self, port: int):
        inner = {
            "currentProfileId": "test-profile",
            "patchClashConfig": {"mixed-port": port},
            "vpnProps": {"enable": True},
            "networkProps": {"systemProxy": True},
        }
        outer = {"flutter.config": json.dumps(inner)}
        (self.clash_root / "shared_preferences.json").write_text(
            json.dumps(outer), encoding="utf-8"
        )

    def install_profile(self):
        self.profile.write_text("# existing user profile\n", encoding="utf-8")
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(INSTALLER),
                "-Mode",
                "Install",
                "-DefaultPort",
                "7890",
                "-CliTimeZone",
                "America/Los_Angeles",
                "-ProfilePath",
                str(self.profile),
            ],
            text=True,
            capture_output=True,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        text = self.profile.read_text(encoding="utf-8-sig")
        self.assertIn("# existing user profile", text)
        self.assertIn("# === flclash-skill windows env begin ===", text)

    def run_profile(self, body: str):
        env = os.environ.copy()
        env["APPDATA"] = str(self.appdata)
        command = (
            f". {ps_quote(self.profile)}; "
            + body
        )
        return subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                command,
            ],
            env=env,
            text=True,
            capture_output=True,
            timeout=20,
        )

    def create_fake_cli(self, name: str, sentinel: Path):
        (self.bin_dir / f"{name}.cmd").write_text(
            f"@echo off\r\necho invoked>{sentinel}\r\necho FAKE-{name.upper()}\r\n",
            encoding="ascii",
        )

    def test_profile_discovers_mixed_port_from_flclash(self):
        self.write_flclash_state(54321)
        self.install_profile()

        result = self.run_profile("Write-Output ('PORT=' + (Get-FlClashProxyPort))")

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PORT=54321", result.stdout)

    def test_listening_port_auto_configures_proxy_and_runs_codex(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = listener.getsockname()[1]
        self.addCleanup(listener.close)
        self.write_flclash_state(port)
        sentinel = self.root / "codex-invoked.txt"
        self.create_fake_cli("codex", sentinel)
        self.install_profile()

        body = (
            f"$env:PATH={ps_quote(str(self.bin_dir) + ';')}+$env:PATH; "
            "codex; "
            "Write-Output ('HTTP_PROXY=' + $env:HTTP_PROXY)"
        )
        result = self.run_profile(body)

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(sentinel.exists(), result.stdout + result.stderr)
        self.assertIn(f"HTTP_PROXY=http://127.0.0.1:{port}", result.stdout)

    def test_missing_port_blocks_claude_without_invoking_command(self):
        self.write_flclash_state(65432)
        sentinel = self.root / "claude-invoked.txt"
        self.create_fake_cli("claude", sentinel)
        self.install_profile()

        body = (
            f"$env:PATH={ps_quote(str(self.bin_dir) + ';')}+$env:PATH; "
            "claude"
        )
        result = self.run_profile(body)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())
        self.assertIn("FAIL-CLOSED", result.stdout + result.stderr)

    def test_proxy_off_keeps_codex_blocked_while_port_is_listening(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = listener.getsockname()[1]
        self.addCleanup(listener.close)
        self.write_flclash_state(port)
        sentinel = self.root / "codex-invoked.txt"
        self.create_fake_cli("codex", sentinel)
        self.install_profile()

        body = (
            f"$env:PATH={ps_quote(str(self.bin_dir) + ';')}+$env:PATH; "
            "proxy_off | Out-Null; codex"
        )
        result = self.run_profile(body)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())
        self.assertIn("FAIL-CLOSED", result.stdout + result.stderr)

    def test_unknown_listener_is_not_accepted_as_flclash(self):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen(8)
        port = listener.getsockname()[1]
        self.addCleanup(listener.close)
        sentinel = self.root / "claude-invoked.txt"
        self.create_fake_cli("claude", sentinel)
        self.install_profile()

        body = (
            f"$global:FlClashProxyDefaultPort={port}; "
            f"$env:PATH={ps_quote(str(self.bin_dir) + ';')}+$env:PATH; "
            "claude"
        )
        result = self.run_profile(body)

        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(sentinel.exists())
        self.assertIn("FAIL-CLOSED", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
