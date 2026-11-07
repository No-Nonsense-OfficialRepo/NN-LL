"""Recovery must tolerate removed interfaces without modifying another adapter."""
import json
import tempfile
import unittest
from pathlib import Path
from lantool.netcore.adapter import AdapterSwitcher
from unittest.mock import patch
import subprocess
import pytest
from lantool.netcore import adapter


def test_adapter_powershell_timeout_is_bounded():
    with patch.object(adapter.subprocess, 'run', side_effect=subprocess.TimeoutExpired('powershell', 30)) as run:
        with pytest.raises(RuntimeError, match='timed out'):
            adapter._ps('Get-NetAdapter')
    assert run.call_args.kwargs['timeout'] == 30


def test_interrupted_state_replace_keeps_previous_record(tmp_path):
    path = tmp_path / 'state.json'
    original = {'active': True, 'alias': 'VLA', 'old_metric': 35}
    path.write_text(json.dumps(original))
    switcher = AdapterSwitcher(path)
    with patch.object(adapter.os, 'replace', side_effect=PermissionError('locked')):
        with pytest.raises(PermissionError):
            switcher._save({'active': False})
    assert json.loads(path.read_text()) == original
    assert list(tmp_path.glob('*.tmp')) == []


@pytest.mark.parametrize('contents', ['{', '[]', '{"active": true, "alias": "VLA", "old_metric": "bad"}'])
def test_corrupt_recovery_does_not_change_any_adapter(tmp_path, contents):
    path = tmp_path / 'state.json'
    path.write_text(contents)
    with patch.object(adapter, '_ps') as run:
        with pytest.raises(RuntimeError, match='recovery record'):
            AdapterSwitcher(path, run=run).recover_after_crash()
    run.assert_not_called()
    assert path.read_text() == contents


def test_restore_preserves_automatic_metric_mode(tmp_path):
    calls = []
    def runner(command):
        calls.append(command)
        return json.dumps(dict(InterfaceIndex=43, InterfaceAlias='VLA', InterfaceMetric=35, AutomaticMetric=1))
    switcher = AdapterSwitcher(tmp_path / 'state.json', run=runner)
    switcher.prefer_zerotier('VLA')
    switcher.restore()
    assert '-AutomaticMetric Enabled' in calls[-1]


class AdapterRecoveryTests(unittest.TestCase):
    def test_preference_requires_private_marker_and_never_matches_other_zerotiers(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            def runner(command):
                calls.append(command)
                return json.dumps(dict(InterfaceIndex=43, InterfaceAlias='VLA [room]', InterfaceMetric=35))
            AdapterSwitcher(Path(temp)/'state.json', run=runner).prefer_zerotier_for_ip('VLA [room]', '10.147.20.5')
            self.assertIn("$entry.ComponentId -ine 'zttap300'", calls[0])
            self.assertIn("$entry._VLATapIdentifier -cnotmatch '^[0-9a-f]{16}$'", calls[0])
            self.assertIn('vla-devices.d', calls[0])
            self.assertIn('Test-VlaAdapter $vlaDevice', calls[0])
            self.assertNotIn("InterfaceDescription -match 'ZeroTier'", calls[0])
            self.assertIn('-InterfaceIndex 43', calls[1])

    def test_stale_index_is_guarded_and_session_cleared(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            path.write_text(json.dumps(dict(active=True,interface_index=43,
                                           alias="ZeroTier One [old]",old_metric=35)))
            calls=[]
            adapter=AdapterSwitcher(path,run=lambda command:calls.append(command))
            self.assertTrue(adapter.recover_after_crash())
            self.assertIn('Get-NetIPInterface -InterfaceIndex 43 -AddressFamily IPv4',calls[0])
            self.assertIn('-ErrorAction SilentlyContinue',calls[0])
            self.assertIn("$iface.InterfaceAlias -eq 'ZeroTier One [old]'",calls[0])
            self.assertIn('$iface | Set-NetIPInterface',calls[0])
            self.assertFalse(json.loads(path.read_text())['active'])
            self.assertFalse(adapter.recover_after_crash())

    def test_real_restore_failure_keeps_recovery_state(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'state.json'
            path.write_text(json.dumps(dict(active=True,interface_index=43,
                                           alias='ZeroTier',old_metric=35)))
            def denied(command):
                raise RuntimeError('Access denied')
            with self.assertRaises(RuntimeError):
                AdapterSwitcher(path,run=denied).restore()
            self.assertTrue(json.loads(path.read_text())['active'])
