"""Package checks use fixtures and mocked trust; nothing is installed or signed."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts import assemble_vla_runtime as assembly
from silent_tunnel import backend, installer
from tests.test_installer_retry import native_fixture, FIXTURE_DRIVER_HASHES


def inputs(root):
    root = Path(root)
    native_fixture(root / "signed")
    service = root / "signed/vla-service.exe"
    driver = root / "signed/driver"
    tool = root / "sdk/signtool.exe"
    tool.parent.mkdir()
    tool.write_bytes(b"verification tool fixture")
    return service, driver, tool, root / "published/vla"


class VlaPackageAssemblyTests(unittest.TestCase):
    def setUp(self):
        driver_hashes = patch.object(backend, "SHARED_DRIVER_SHA256", FIXTURE_DRIVER_HASHES)
        driver_hashes.start()
        self.addCleanup(driver_hashes.stop)

    def test_verified_package_includes_exact_hashes_and_supplied_notices(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            notice = Path(folder) / "THIRD-PARTY-NOTICES.md"
            notice.write_text("Native attribution notice")
            licenses = Path(folder) / "licenses"
            licenses.mkdir()
            (licenses / "GPL-2.0-only.txt").write_text("Supplied license text")
            commands = []

            def verify(command, **kwargs):
                self.assertFalse(output.exists())
                self.assertTrue(Path(command[-1]).is_file())
                commands.append(command)
                return Mock(returncode=0, stdout="Verified", stderr="")

            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "verify_authenticode", return_value=True), \
                    patch.object(assembly.subprocess, "run", side_effect=verify), \
                    patch.object(installer, "validate_package", wraps=installer.validate_package) as validate:
                self.assertEqual(assembly.assemble(service, driver, output, notices=[notice, licenses], signtool=tool), output)
            manifest = json.loads((output / "manifest.json").read_text())
            for name, digest in manifest["files"].items():
                self.assertEqual(digest, hashlib.sha256((output / name).read_bytes()).hexdigest())
            self.assertEqual((output / "notices/THIRD-PARTY-NOTICES.md").read_text(), notice.read_text())
            self.assertEqual((output / "notices/GPL-2.0-only.txt").read_text(), "Supplied license text")
            self.assertEqual(manifest["service_name"], "LanLauncherVLA")
            self.assertEqual(manifest["api_port"], 47993)
            self.assertEqual(manifest["schema"], 2)
            self.assertEqual(manifest["driver_mode"], "shared-signed")
            self.assertIs(manifest["driver_remove_on_uninstall"], False)
            self.assertIs(manifest["service_signature_required"], False)
            self.assertEqual(len(commands), 2)
            self.assertTrue(all(command[1:4] == ["verify", "/kp", "/c"] for command in commands))
            self.assertEqual({Path(command[-1]).suffix for command in commands}, {".inf", ".sys"})
            self.assertTrue(all(call.kwargs == {"check_signatures": True} for call in validate.call_args_list))
            self.assertEqual(list(output.parent.glob(".vla-assembly-*")), [])

    def test_unsigned_kernel_inputs_never_publish_or_execute_verifier(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            with patch.object(installer, "verify_driver_catalog", return_value=False), \
                    patch.object(assembly.subprocess, "run") as run:
                with self.assertRaisesRegex(assembly.AssemblyError, "original unchanged signed driver"):
                    assembly.assemble(service, driver, output, signtool=tool)
                run.assert_not_called()
            self.assertFalse(output.exists())
            self.assertEqual(list(output.parent.glob(".vla-assembly-*")), [])

    def test_missing_driver_file_fails_before_creating_output_parent(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            (driver / "zttap300.cat").unlink()
            with self.assertRaisesRegex(assembly.AssemblyError, "Missing finalized signed driver file"):
                assembly.assemble(service, driver, output, signtool=tool)
            self.assertFalse(output.parent.exists())

    def test_missing_native_provenance_is_actionable_and_never_publishes(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            (service.parent / backend.SERVICE_PROVENANCE).unlink()
            with self.assertRaisesRegex(assembly.AssemblyError, "use --provenance"):
                assembly.assemble(service, driver, output, signtool=tool)
            self.assertFalse(output.parent.exists())

    def test_mismatched_signed_catalog_never_publishes(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "verify_authenticode", return_value=True), \
                    patch.object(assembly.subprocess, "run", return_value=Mock(returncode=1, stdout="", stderr="not in catalog")):
                with self.assertRaisesRegex(assembly.AssemblyError, "matching, unchanged INF/SYS"):
                    assembly.assemble(service, driver, output, signtool=tool)
            self.assertFalse(output.exists())

    def test_windows_api_verifies_without_sdk_or_service_publisher_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, _, output = inputs(folder)
            with patch.object(installer, "verify_driver_catalog", return_value=True) as catalog, \
                    patch.object(installer, "verify_authenticode", return_value=False) as publisher, \
                    patch.object(assembly.shutil, "which", return_value=None), \
                    patch.object(assembly.subprocess, "run") as run:
                self.assertEqual(assembly.assemble(service, driver, output), output)
                run.assert_not_called()
                publisher.assert_not_called()
            self.assertEqual(catalog.call_count, 4)
            self.assertTrue(output.exists())

    def test_last_validation_rejects_changed_staging_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)

            def changed(package, verifier):
                (package / "driver/zttap300.sys").write_bytes(b"changed after catalog verification")

            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "verify_authenticode", return_value=True), \
                    patch.object(assembly, "_verify_catalog_membership", side_effect=changed):
                with self.assertRaisesRegex(installer.InstallError, "integrity check"):
                    assembly.assemble(service, driver, output, signtool=tool)
            self.assertFalse(output.exists())
            self.assertEqual(list(output.parent.glob(".vla-assembly-*")), [])

    def test_modified_driver_is_rejected_before_verifier(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            (driver / "zttap300.inf").write_text('Provider="LAN Launcher VLA"\nAddService=vlatap,2,Service\nDevice=root\\vlatap')
            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(assembly.subprocess, "run") as run:
                with self.assertRaisesRegex(assembly.AssemblyError, "byte-for-byte unchanged"):
                    assembly.assemble(service, driver, output, signtool=tool)
                run.assert_not_called()
            self.assertFalse(output.exists())

    def test_existing_output_is_never_replaced(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            output.mkdir(parents=True)
            sentinel = output / "keep.txt"
            sentinel.write_text("Existing package")
            with patch.object(installer, "verify_authenticode") as trust:
                with self.assertRaisesRegex(assembly.AssemblyError, "Output already exists"):
                    assembly.assemble(service, driver, output, signtool=tool)
                trust.assert_not_called()
            self.assertEqual(sentinel.read_text(), "Existing package")

    def test_output_created_during_validation_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)

            def verify(*args):
                output.mkdir()
                (output / "concurrent.txt").write_text("Concurrent output")

            with patch.object(installer, "verify_driver_catalog", return_value=True), \
                    patch.object(installer, "verify_authenticode", return_value=True), \
                    patch.object(assembly, "_verify_catalog_membership", side_effect=verify):
                with self.assertRaisesRegex(assembly.AssemblyError, "appeared during validation"):
                    assembly.assemble(service, driver, output, signtool=tool)
            self.assertEqual((output / "concurrent.txt").read_text(), "Concurrent output")

    def test_git_and_parent_traversal_paths_are_rejected(self):
        for path in (Path("Source/.git/objects"), Path("Source/vendor/../outside")):
            with self.assertRaises(assembly.AssemblyError):
                assembly._checked_path(path)

    def test_junction_ancestor_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "junction/file.txt"
            original = Path.lstat

            def lstat(item):
                if item == path.parent:
                    return Mock(st_mode=0, st_file_attributes=0x400)
                return original(item)

            with patch.object(Path, "lstat", lstat):
                with self.assertRaisesRegex(assembly.AssemblyError, "junctions are refused"):
                    assembly._checked_path(path)

    def test_notices_are_flat_and_case_insensitively_unique(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "a/NOTICE.txt"
            second = root / "b/notice.txt"
            for file in (first, second):
                file.parent.mkdir()
                file.write_text("Attribution")
            with self.assertRaisesRegex(assembly.AssemblyError, "Duplicate notice"):
                assembly._notice_files([first, second])
            with self.assertRaisesRegex(assembly.AssemblyError, "directories must be flat"):
                assembly._notice_files([root])

    def test_cli_reports_failure_and_never_claims_success(self):
        with tempfile.TemporaryDirectory() as folder:
            service, driver, tool, output = inputs(folder)
            with patch.object(installer, "verify_driver_catalog", return_value=False), \
                    patch.object(assembly.sys, "stderr") as stderr, \
                    patch.object(assembly.sys, "stdout") as stdout:
                self.assertEqual(assembly.main(["--service", str(service), "--driver", str(driver), "--output", str(output)]), 1)
            self.assertIn("original unchanged signed driver", "".join(call.args[0] for call in stderr.write.call_args_list))
            stdout.write.assert_not_called()
