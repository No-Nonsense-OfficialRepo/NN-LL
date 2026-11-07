"""Native VLA packages must never fall back to the ordinary ZeroTier product."""
import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from silent_tunnel import backend, installer
from silent_tunnel.errors import InstallError


FIXTURE_CONTENTS = {
        backend.SERVICE_EXECUTABLE: b"native VLA service fixture LanLauncherVLA",
        "driver/zttap300.inf": b'Provider="ZeroTier"\nCatalogFile=zttap300.cat\nAddService=zttap300,2,Service\nDevice=root\\zttap300\n',
        "driver/zttap300.cat": b"catalog fixture",
        "driver/zttap300.sys": b"driver fixture",
    }
FIXTURE_DRIVER_HASHES = {Path(name).name: hashlib.sha256(data).hexdigest()
                         for name, data in FIXTURE_CONTENTS.items() if name.startswith("driver/")}
USER_SID = "S-1-5-21-111-222-333-1000"


def native_fixture(directory):
    directory = Path(directory)
    contents = dict(FIXTURE_CONTENTS)
    provenance = {"schema": 1, "backend": backend.BACKEND_ID, "service_name": backend.SERVICE_NAME,
                  "display_name": backend.SERVICE_DISPLAY_NAME, "executable": backend.SERVICE_EXECUTABLE,
                  "api_port": backend.DEFAULT_PORT, "driver_mode": backend.DRIVER_MODE,
                  "driver_service": backend.DRIVER_SERVICE, "driver_component": backend.DRIVER_COMPONENT,
                  "source_commit": backend.NATIVE_SOURCE_COMMIT, "patch_sha256": "0" * 64,
                  "executable_sha256": hashlib.sha256(contents[backend.SERVICE_EXECUTABLE]).hexdigest()}
    contents[backend.SERVICE_PROVENANCE] = json.dumps(provenance).encode("utf-8")
    manifest = {**installer._MANIFEST_IDENTITY, "files": {}}
    for name, data in contents.items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        manifest["files"][name] = hashlib.sha256(data).hexdigest()
    (directory / backend.MANIFEST_NAME).write_text(json.dumps(manifest), "utf-8")
    return directory, manifest


class InstallerRetryTests(unittest.TestCase):
    def setUp(self):
        self.driver_hashes = patch.object(backend, "SHARED_DRIVER_SHA256", FIXTURE_DRIVER_HASHES)
        self.driver_hashes.start()
        self.addCleanup(self.driver_hashes.stop)
        registered = patch.object(installer, "_registered_shared_driver", return_value=None)
        registered.start()
        self.addCleanup(registered.stop)

    def test_service_name_does_not_hide_wrong_executable(self):
        with patch.object(installer, "is_windows", return_value=True), \
                patch.object(installer, "_service_exists", return_value=True), \
                patch.object(installer, "_service_is_owned", return_value=False):
            self.assertFalse(installer.is_installed())

    def test_access_grant_targets_only_installing_user_and_exact_key(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder)
            (home / "authtoken.secret").write_text("fixture key")
            with patch.object(backend, "default_home", return_value=home), \
                    patch.object(installer.subprocess, "run", return_value=Mock(returncode=0)) as run:
                installer._grant_vla_token_access(USER_SID)
            command = run.call_args.args[0]
            self.assertEqual(command[1:], [str(home / "authtoken.secret"), "/grant:r", f"*{USER_SID}:(R)"])
            self.assertNotIn("fixture key", str(command))

    def test_access_grant_rejects_invalid_sid_before_mutation(self):
        with patch.object(installer.subprocess, "run") as run:
            with self.assertRaisesRegex(InstallError, "user identity is invalid"):
                installer._grant_vla_token_access("BUILTIN\\Users")
            run.assert_not_called()

    def test_missing_artifacts_fail_before_any_elevation(self):
        with patch.object(installer, "is_windows", return_value=True), \
                patch.object(installer, "bundled_package_path", return_value=None), \
                patch.object(installer, "run_elevated") as elevate:
            with self.assertRaisesRegex(InstallError, "private VLA service and unchanged signed shared driver"):
                installer.install(Path("unused"))
            elevate.assert_not_called()

    def test_private_service_without_shared_driver_is_not_ready(self):
        with patch.object(installer, "is_windows", return_value=True), \
                patch.object(installer, "_service_exists", return_value=True), \
                patch.object(installer, "_service_is_owned", return_value=True), \
                patch.object(installer, "validate_package", return_value={}), \
                patch.object(installer, "_shared_driver_present", return_value=False):
            self.assertFalse(installer.is_installed())

    def test_staged_shared_driver_can_be_reused_before_first_device(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            store = root / "System32/DriverStore/FileRepository/zttap300.inf_amd64_fixture"
            store.mkdir(parents=True)
            for name, data in FIXTURE_CONTENTS.items():
                if name.startswith("driver/"):
                    (store / Path(name).name).write_bytes(data)
            with patch.dict(os.environ, {"SystemRoot": str(root)}), \
                    patch.object(installer, "is_windows", return_value=True), \
                    patch("winreg.OpenKey", side_effect=FileNotFoundError):
                self.assertTrue(installer._shared_driver_present())

    def test_native_package_staged_and_reverified_before_elevation(self):
        with tempfile.TemporaryDirectory() as folder:
            package, _ = native_fixture(Path(folder) / "share")
            staged = []

            def elevated(action, *, path, user_sid):
                self.assertEqual(action, "install_vla")
                self.assertEqual(user_sid, USER_SID)
                path = Path(path)
                self.assertNotEqual(path, package)
                self.assertEqual((path / backend.SERVICE_EXECUTABLE).read_bytes(),
                                 (package / backend.SERVICE_EXECUTABLE).read_bytes())
                staged.append(path)

            with patch.object(installer, "is_windows", return_value=True), \
                    patch.object(installer, "bundled_package_path", return_value=package), \
                    patch.object(installer, "verify_driver_catalog", return_value=True) as verify, \
                    patch.object(installer, "_service_exists", return_value=False), \
                    patch.object(installer, "_check_port_available"), \
                    patch.object(installer, "_current_user_sid", return_value=USER_SID), \
                    patch.object(installer, "run_elevated", side_effect=elevated), \
                    patch.object(installer, "is_installed", return_value=True):
                installer.install(Path(folder) / "local")
            self.assertEqual(verify.call_count, 4)
            self.assertFalse(staged[0].exists())

    def test_hash_tampering_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            package, _ = native_fixture(folder)
            (package / backend.SERVICE_EXECUTABLE).write_bytes(b"changed")
            with self.assertRaisesRegex(InstallError, "integrity check"):
                installer.validate_package(package)

    def test_shared_driver_modification_is_rejected_even_with_recomputed_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            package, manifest = native_fixture(folder)
            inf = package / "driver/zttap300.inf"
            inf.write_text('Provider="LAN Launcher VLA"\nAddService=vlatap,2,Service\nDevice=root\\vlatap')
            manifest["files"]["driver/zttap300.inf"] = hashlib.sha256(inf.read_bytes()).hexdigest()
            (package / backend.MANIFEST_NAME).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InstallError, "byte-for-byte unchanged"):
                installer.validate_package(package)

    def test_manifest_cannot_escape_package_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            package, manifest = native_fixture(folder)
            manifest["files"]["../outside.exe"] = "0" * 64
            (package / backend.MANIFEST_NAME).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InstallError, "invalid file entry"):
                installer.validate_package(package, check_signatures=False)

    def test_unsigned_kernel_package_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            package, _ = native_fixture(folder)
            with patch.object(installer, "verify_driver_catalog", return_value=False):
                with self.assertRaisesRegex(InstallError, "driver signature and catalog membership"):
                    installer.validate_package(package)

    def test_unsigned_private_service_allowed_with_matching_native_provenance(self):
        with tempfile.TemporaryDirectory() as folder:
            package, _ = native_fixture(folder)
            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "verify_authenticode", return_value=False) as publisher:
                installer.validate_package(package)
            publisher.assert_not_called()

    def test_required_publisher_signature_policy_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            package, manifest = native_fixture(folder)
            manifest["service_signature_required"] = True
            (package / backend.MANIFEST_NAME).write_text(json.dumps(manifest))
            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "verify_authenticode", return_value=False):
                with self.assertRaisesRegex(InstallError, "publisher signature"):
                    installer.validate_package(package)

    def test_mismatched_native_provenance_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            package, manifest = native_fixture(folder)
            provenance = package / backend.SERVICE_PROVENANCE
            record = json.loads(provenance.read_text())
            record["service_name"] = "ZeroTierOneService"
            provenance.write_text(json.dumps(record))
            manifest["files"][backend.SERVICE_PROVENANCE] = hashlib.sha256(provenance.read_bytes()).hexdigest()
            (package / backend.MANIFEST_NAME).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InstallError, "provenance does not match"):
                installer.validate_package(package)

    def test_renamed_stock_executable_cannot_be_treated_as_private_service(self):
        with tempfile.TemporaryDirectory() as folder:
            package, manifest = native_fixture(folder)
            binary = package / backend.SERVICE_EXECUTABLE
            binary.write_bytes(b"ordinary stock service fixture")
            digest = hashlib.sha256(binary.read_bytes()).hexdigest()
            manifest["files"][backend.SERVICE_EXECUTABLE] = digest
            provenance = package / backend.SERVICE_PROVENANCE
            record = json.loads(provenance.read_text())
            record["executable_sha256"] = digest
            provenance.write_text(json.dumps(record))
            manifest["files"][backend.SERVICE_PROVENANCE] = hashlib.sha256(provenance.read_bytes()).hexdigest()
            (package / backend.MANIFEST_NAME).write_text(json.dumps(manifest))
            with self.assertRaisesRegex(InstallError, "private service identity"):
                installer.validate_package(package)

    def test_elevated_install_registers_only_fixed_vla_identity(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package, _ = native_fixture(root / "package")
            with patch.object(installer, "is_windows", return_value=True), \
                    patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "_service_exists", return_value=False), \
                    patch.object(installer, "_shared_driver_present", return_value=False), \
                    patch.object(installer, "_check_port_available"), \
                    patch.object(backend, "install_home", return_value=root / "installed"), \
                    patch.object(backend, "default_home", return_value=root / "state"), \
                    patch.object(installer.subprocess, "run", return_value=Mock(returncode=0)) as run, \
                    patch.object(installer, "start_service") as start, \
                    patch.object(installer, "_grant_vla_token_access") as grant:
                installer.install_native_package(package, USER_SID)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][1:3], ["/add-driver", str(root / "installed/driver/zttap300.inf")])
            self.assertNotIn("/install", commands[0])
            self.assertNotIn("/delete-driver", str(commands))
            self.assertEqual(commands[1][1:3], ["create", "LanLauncherVLA"])
            self.assertIn("VLA - Virtual LAN Adaptor", commands[1])
            self.assertIn("name=LanLauncherVLA-Transport-In", commands[2])
            self.assertIn("program=" + str(root / "installed/vla-service.exe"), commands[2])
            self.assertNotIn("ZeroTierOneService", str(commands))
            start.assert_called_once_with()
            grant.assert_called_once_with(USER_SID)

    def test_uninstall_routes_only_scoped_vla_removal(self):
        with patch.object(installer, "is_windows", return_value=True), \
                patch.object(installer, "_service_exists", return_value=True), \
                patch.object(installer, "run_elevated", return_value={"report": {"issues": [], "reboot": False}}) as elevate:
            self.assertTrue(installer.uninstall())
            elevate.assert_called_once_with("wipe_vla")

    def test_existing_shared_driver_skips_staging_and_global_driver_operations(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package, _ = native_fixture(root / "package")
            with patch.object(installer, "is_windows", return_value=True), \
                    patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "_service_exists", return_value=False), \
                    patch.object(installer, "_shared_driver_present", return_value=True), \
                    patch.object(installer, "_check_port_available"), \
                    patch.object(backend, "install_home", return_value=root / "installed"), \
                    patch.object(backend, "default_home", return_value=root / "state"), \
                    patch.object(installer.subprocess, "run", return_value=Mock(returncode=0)) as run, \
                    patch.object(installer, "start_service"), \
                    patch.object(installer, "_grant_vla_token_access"):
                installer.install_native_package(package, USER_SID)
            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][1:3], ["create", "LanLauncherVLA"])
            self.assertEqual(len(commands), 2)
            self.assertNotIn("pnputil", str(commands))
            self.assertNotIn("delete", str(commands))

    def test_mismatched_existing_shared_driver_blocks_before_any_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package, _ = native_fixture(root / "package")
            existing = root / "existing.sys"
            existing.write_bytes(b"another application's driver build")
            with patch.object(installer, "is_windows", return_value=True), \
                    patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "_service_exists", return_value=False), \
                    patch.object(installer, "_registered_shared_driver", return_value=existing), \
                    patch.object(backend, "install_home", return_value=root / "installed"), \
                    patch.object(backend, "default_home", return_value=root / "state"), \
                    patch.object(installer.subprocess, "run") as run, \
                    patch.object(installer, "run_elevated") as elevate:
                with self.assertRaisesRegex(InstallError, "left it unchanged to preserve other applications"):
                    installer.install_native_package(package, USER_SID)
                with patch.object(installer, "bundled_package_path", return_value=package):
                    with self.assertRaisesRegex(InstallError, "matching driver build"):
                        installer.install(root / "downloads")
                run.assert_not_called()
                elevate.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"another application's driver build")
            self.assertFalse((root / "installed").exists())
            self.assertFalse((root / "state").exists())

    def test_matching_shared_driver_is_compatible_but_not_claimed(self):
        with tempfile.TemporaryDirectory() as folder:
            existing = Path(folder) / "zttap300.sys"
            existing.write_bytes(FIXTURE_CONTENTS["driver/zttap300.sys"])
            with patch.object(installer, "_registered_shared_driver", return_value=existing):
                installer._check_shared_driver_compatibility()

    def test_partial_removal_cannot_report_success(self):
        with patch.object(installer, "is_windows", return_value=True), \
                patch.object(installer, "_service_exists", return_value=True), \
                patch.object(installer, "run_elevated", return_value={"report": {"issues": ["driver busy"]}}):
            with self.assertRaisesRegex(InstallError, "driver busy"):
                installer.uninstall()

    def test_port_collision_closes_probes_without_elevation(self):
        sock = Mock()
        sock.bind.side_effect = OSError("in use")
        with patch.object(installer.socket, "socket", return_value=sock), \
                patch.object(installer, "run_elevated") as elevate:
            with self.assertRaisesRegex(InstallError, "47993 is in use"):
                installer._check_port_available()
        sock.close.assert_called_once_with()
        elevate.assert_not_called()
