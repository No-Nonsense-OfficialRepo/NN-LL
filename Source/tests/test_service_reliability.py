"""Mocked interruption and identity tests; never operate on live Windows state."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from silent_tunnel import admin_actions as admin, backend, installer, profile_records as profiles


def test_helper_timeout_keeps_request_and_staged_inputs(tmp_path):
    request = None
    with pytest.raises(admin.ElevatedOperationTimeout, match='may still be running'):
        with admin.operation_directory('request-', tmp_path) as directory:
            request = Path(directory)
            (request / 'request.json').write_text('{}')
            kernel = SimpleNamespace(WaitForSingleObject=Mock(return_value=0x102))
            admin._wait_for_helper(kernel, 1, 'prepare_pc', request)
    assert (request / 'request.json').exists()
    kernel.WaitForSingleObject.assert_called_once_with(1, 900_000)


def test_successful_helper_removes_request(tmp_path):
    with admin.operation_directory('request-', tmp_path) as directory:
        request = Path(directory)
    assert not request.exists()


def test_profile_journal_merges_before_mutation_and_retains_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'default_home', lambda: tmp_path)
    first = dict(index=4, guid='11111111-1111-1111-1111-111111111111', profile='LAN', profile_id='network-1', category='Public')
    second = dict(index=8, guid='22222222-2222-2222-2222-222222222222', profile='WiFi', profile_id='network-2', category='Public')
    monkeypatch.setattr(profiles, 'identity', lambda i: {4: first, 8: second}[i])
    def mutate(row, category):
        assert row in profiles.load()['profiles']  # journal precedes mutation
        if row['index'] == 8:
            raise RuntimeError('Windows failed')
    monkeypatch.setattr(profiles, 'set_checked', mutate)
    profiles.make_private([4])
    with pytest.raises(RuntimeError, match='Windows failed'):
        profiles.make_private([8])
    assert profiles.load()['profiles'] == [first, second]
    monkeypatch.setattr(profiles, 'set_checked', Mock())
    profiles.restore()
    assert not profiles.record_path().exists()


def test_profile_restore_retains_unrestored_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'default_home', lambda: tmp_path)
    rows = [dict(index=i, guid=f'{i:08d}-1111-1111-1111-111111111111', profile='LAN', category='Public') for i in (4, 8)]
    profiles.save({'changed': True, 'profiles': rows})
    change = Mock(side_effect=[None, RuntimeError('identity changed')])
    monkeypatch.setattr(profiles, 'set_checked', change)
    with pytest.raises(RuntimeError, match='identity changed'):
        profiles.restore()
    assert profiles.load()['profiles'] == rows[1:]


def test_legacy_index_record_is_never_applied(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'default_home', lambda: tmp_path)
    profiles.save({'changed': True, 'indexes': [4]})
    run = Mock()
    monkeypatch.setattr(profiles, '_ps', run)
    with pytest.raises(RuntimeError, match='lacks adapter identity'):
        profiles.restore()
    run.assert_not_called()
    assert profiles.record_path().exists()


def test_profile_restore_attempts_later_rows_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'default_home', lambda: tmp_path)
    rows = [dict(index=i, category='Public') for i in (4, 8, 9)]
    profiles.save({'changed': True, 'profiles': rows})
    change = Mock(side_effect=[RuntimeError('stale adapter'), None, None])
    monkeypatch.setattr(profiles, 'set_checked', change)
    with pytest.raises(RuntimeError, match='stale adapter'):
        profiles.restore()
    assert change.call_count == 3
    assert profiles.load()['profiles'] == rows[:1]


def test_profile_change_revalidates_adapter_and_network_in_same_command(monkeypatch):
    run = Mock()
    monkeypatch.setattr(profiles, '_ps', run)
    profiles.set_checked(dict(index=4, guid='11111111-1111-1111-1111-111111111111', profile="LAN's name", profile_id='network-1'), 'Public')
    command = run.call_args.args[0]
    assert "InterfaceGuid.ToString()" in command
    assert "$p.Name -cne 'LAN''s name'" in command
    assert "$p.InstanceID -cne 'network-1'" in command
    assert '-NetworkCategory Public -ErrorAction Stop' in command


def test_profile_subprocess_failure_is_not_success(monkeypatch):
    monkeypatch.setattr(profiles.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=1, stdout='')))
    with pytest.raises(RuntimeError, match='could not read or restore'):
        profiles._ps('mock command')


def test_interrupted_native_install_resumes_exact_package(tmp_path, monkeypatch):
    package = tmp_path / 'package'
    package.mkdir()
    (package / backend.MANIFEST_NAME).write_text('{}')
    (package / 'service.bin').write_bytes(b'valid')
    destination = tmp_path / 'installed'
    manifest = {'files': {'service.bin': 'verified'}}
    monkeypatch.setattr(backend, 'install_home', lambda: destination)
    monkeypatch.setattr(backend, 'default_home', lambda: tmp_path / 'state')
    monkeypatch.setattr(installer, 'is_windows', lambda: True)
    monkeypatch.setattr(installer, 'validate_package', lambda *a, **k: manifest)
    monkeypatch.setattr(installer, '_service_exists', lambda: False)
    monkeypatch.setattr(installer, '_check_shared_driver_compatibility', lambda: None)
    monkeypatch.setattr(installer, '_check_port_available', lambda: None)
    monkeypatch.setattr(installer, '_shared_driver_present', lambda: True)
    monkeypatch.setattr(installer.subprocess, 'run', Mock(return_value=SimpleNamespace(returncode=0)))
    monkeypatch.setattr(installer, 'start_service', Mock(side_effect=RuntimeError('interrupted')))
    monkeypatch.setattr(installer, '_grant_vla_token_access', Mock())
    with pytest.raises(RuntimeError, match='interrupted'):
        installer.install_native_package(package, 'S-1-5-21-1-2-3-4')
    assert installer.installation_pending()
    monkeypatch.setattr(installer, '_service_exists', lambda: True)
    monkeypatch.setattr(installer, '_service_is_owned', lambda: True)
    monkeypatch.setattr(installer, 'start_service', Mock())
    installer.install_native_package(package, 'S-1-5-21-1-2-3-4')
    assert not installer.installation_pending()
    assert (destination / 'service.bin').read_bytes() == b'valid'
