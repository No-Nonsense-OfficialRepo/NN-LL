"""Isolation tests use temporary data and mocks; no service or driver is changed."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from silent_tunnel import admin_actions, backend
from silent_tunnel.errors import ServiceError
from silent_tunnel.local import LocalClient


class VlaBackendTests(unittest.TestCase):
    def test_identity_is_separate_from_ordinary_zerotier(self):
        self.assertEqual(backend.SERVICE_NAME, "LanLauncherVLA")
        self.assertEqual(backend.DEFAULT_PORT, 47993)
        self.assertEqual(backend.default_home().name, "VLA")
        self.assertNotIn("ZeroTier", str(backend.default_home()))
        self.assertEqual(backend.service_command(), [str(backend.install_home() / "vla-service.exe")])
        self.assertEqual(backend.DRIVER_MODE, "shared-signed")
        self.assertEqual(backend.DRIVER_SERVICE, "zttap300")

    def test_invalid_catalog_member_cannot_pass_driver_trust(self):
        with tempfile.TemporaryDirectory() as folder:
            catalog = Path(folder) / "invalid.cat"
            member = Path(folder) / "invalid.sys"
            catalog.write_bytes(b"not a catalog")
            member.write_bytes(b"not a driver")
            self.assertFalse(admin_actions.verify_driver_catalog(catalog, member))

    def test_default_port_does_not_use_9993(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(LocalClient(home=Path(folder))._get_port(), 47993)

    def test_wrong_port_file_is_rejected_before_http_call(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / backend.PORT_FILE).write_text("9993")
            with patch("silent_tunnel.local.request_json") as request:
                with self.assertRaisesRegex(ServiceError, "unexpected API port"):
                    LocalClient(home=home, token="vla-key").status()
                request.assert_not_called()

    def test_ordinary_zerotier_user_token_is_never_used(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / ".zeroTierOneAuthToken").write_text("ordinary-user-token")
            with patch.object(Path, "home", return_value=home):
                with self.assertRaisesRegex(ServiceError, "VLA isn't ready"):
                    LocalClient(home=home / "private")._get_token()

    def test_client_uses_only_its_own_token_and_api_port(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "authtoken.secret").write_text("vla-key")
            with patch("silent_tunnel.local.request_json", return_value={}) as request:
                LocalClient(home=home).status()
            self.assertEqual(request.call_args.args[1], "http://127.0.0.1:47993/status")
            self.assertEqual(request.call_args.args[2], {"X-ZT1-Auth": "vla-key"})

    def test_legacy_elevated_operations_are_rejected(self):
        with patch.object(admin_actions.subprocess, "run") as run:
            for action in ("install_msi", "uninstall_msi", "wipe_zerotier"):
                with self.assertRaisesRegex(ValueError, "Unknown administrative operation"):
                    admin_actions._run_action({"action": action, "path": "ZeroTierOne.msi"})
            run.assert_not_called()

    def test_vla_wipe_preserves_structured_report(self):
        report = {"report": {"issues": ["driver busy"], "reboot": True}}
        with patch("silent_tunnel.wipe.wipe_windows", return_value=report) as wipe:
            self.assertEqual(admin_actions._run_action({"action": "wipe_vla"}), report)
        wipe.assert_called_once_with()
