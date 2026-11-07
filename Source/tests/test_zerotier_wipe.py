"""Test destructive-operation routing and reporting without touching Windows."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from silent_tunnel import admin_actions
from silent_tunnel.wipe import SCRIPT, wipe_windows
from contextlib import nullcontext
import pytest


@pytest.fixture(autouse=True)
def isolate_system_profile_recovery(monkeypatch):
    monkeypatch.setattr('silent_tunnel.wipe.profile_records.transaction', nullcontext)
    monkeypatch.setattr('silent_tunnel.wipe.profile_records._restore_unlocked', lambda: None)


class WipeTests(unittest.TestCase):
    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows registry scan')
    def test_adapter_scan_avoids_protected_keys_but_propagates_adapter_denial(self):
        helper = re.search(r'function AdapterEntries \{.*?\n\}(?=\nfunction OwnedDevices)', SCRIPT, re.S).group()
        harness = r'''
$ErrorActionPreference = 'Stop'
$netClass = 'HKLM:\SYSTEM\CurrentControlSet\Control\Class\{4D36E972-E325-11CE-BFC1-08002BE10318}'
function Get-Item {
    $root = New-Object PSObject
    $root | Add-Member ScriptMethod GetSubKeyNames { @('0000','Properties','Configuration','0001') }
    $root | Add-Member ScriptMethod Close { }
    $root
}
$script:denyAdapter = $false
function Get-ItemProperty {
    param($LiteralPath, $ErrorAction)
    if ($LiteralPath -notmatch '\\[0-9]{4}$') { throw 'Opened protected non-adapter key' }
    if ($script:denyAdapter) { throw 'Adapter access denied' }
    [pscustomobject]@{ DeviceInstanceID=$LiteralPath }
}
'''
        checks = r'''
if (@(AdapterEntries).Count -ne 2) { throw 'Expected both numbered adapters' }
$script:denyAdapter = $true
try { AdapterEntries; throw 'Denied adapter was silently ignored' }
catch { if ($_.Exception.Message -ne 'Adapter access denied') { throw } }
exit 0
'''
        import os
        powershell = Path(os.environ['SystemRoot']) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
        import base64
        command = base64.b64encode((harness + helper + checks).encode('utf-16-le')).decode('ascii')
        result = subprocess.run([str(powershell), '-NoProfile', '-NonInteractive', '-EncodedCommand',
                                 command], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_script_targets_private_vla_only(self):
        for shared in ('ZeroTierOneService', 'zerotier-one_x64',
                       'ZeroTier*', '.zeroTierOneAuthToken', 'msiexec', 'HKEY_USERS'):
            self.assertNotIn(shared, SCRIPT)
        self.assertIn("$entry.ComponentId -ine 'zttap300'", SCRIPT)
        self.assertIn("$entry._VLATapIdentifier -cnotmatch '^[0-9a-f]{16}$'", SCRIPT)
        self.assertIn('vla-devices.d', SCRIPT)
        self.assertIn('$recorded -ine $entry.DeviceInstanceID', SCRIPT)
        self.assertNotIn('/delete-driver', SCRIPT)
        self.assertNotIn("@('LanLauncherVLA','zttap300')", SCRIPT)
        self.assertNotIn("@('delete', 'zttap300')", SCRIPT)
        self.assertIn('LAN Launcher\\VLA', SCRIPT)
        self.assertIn('unexpected service executable', SCRIPT)
        self.assertIn("$_.Program -eq $nativeExe", SCRIPT)
        self.assertIn("$_.DisplayName -like 'lanlauncher-vla-icmp*'", SCRIPT)
        self.assertIn("'^LANLauncherVLA:[0-9a-fA-F]{16}$'", SCRIPT)

    def test_admin_child_preserves_partial_failure_report(self):
        with tempfile.TemporaryDirectory() as folder:
            request = Path(folder) / 'request.json'
            result = Path(folder) / 'result.json'
            request.write_text(json.dumps({'action': 'wipe_vla', 'result_path': str(result)}))
            report = {'issues': ['Driver locked'], 'reboot': True}
            with patch('silent_tunnel.wipe.wipe_windows', return_value={'report': report}) as wipe:
                self.assertEqual(admin_actions.run_admin_child(str(request)), 0)
            wipe.assert_called_once_with()
            self.assertEqual(json.loads(result.read_text())['report'], report)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows subprocess wrapper')
    def test_plain_fixed_script_and_result(self):
        completed = Mock(returncode=0, stdout='{"issues":[],"reboot":false}', stderr='')
        with patch('silent_tunnel.wipe.subprocess.run', return_value=completed) as run:
            self.assertEqual(wipe_windows(), {'report': {'issues': [], 'reboot': False}})
        args = run.call_args.args[0]
        self.assertEqual(args[-1], SCRIPT)
        self.assertIn('-Command', args)
        self.assertNotIn('-EncodedCommand', args)
        self.assertLess(len(subprocess.list2cmdline(args)), 32767)

    @unittest.skipUnless(__import__('os').name == 'nt', 'Windows subprocess wrapper')
    def test_failed_script_cannot_report_success(self):
        with patch('silent_tunnel.wipe.subprocess.run', return_value=Mock(returncode=1, stderr='Denied')):
            with self.assertRaisesRegex(RuntimeError, 'Denied'):
                wipe_windows()
