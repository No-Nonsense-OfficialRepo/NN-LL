"""Scope, readiness and serialized recovery checks without live Windows changes."""
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from silent_tunnel import admin_actions as admin, backend, profile_records as profiles, wipe
from silent_tunnel.tunnel import Tunnel


def test_helper_wipe_uses_validated_caller_release_root(tmp_path, monkeypatch):
    root = tmp_path / 'release'
    root.mkdir()
    caller = root / 'Client.exe'
    caller.write_bytes(b'fixture')
    helper = root / 'Launcher Bin' / 'Elevation' / 'LAN Helper.exe'
    helper.parent.mkdir(parents=True)
    helper.write_bytes(b'fixture')
    monkeypatch.setattr(admin.sys, 'executable', str(helper))
    run = Mock(return_value={'report': {'issues': []}})
    monkeypatch.setattr(wipe, 'wipe_windows', run)
    admin._run_action({'action': 'wipe_vla', 'caller_program': str(caller)})
    run.assert_called_once_with(root=root)


def test_helper_wipe_without_caller_refuses_scope_guess(monkeypatch):
    monkeypatch.setattr(admin, '_is_helper_process', lambda: True)
    run = Mock()
    monkeypatch.setattr(wipe, 'wipe_windows', run)
    with pytest.raises(ValueError, match='reset scope'):
        admin._run_action({'action': 'wipe_vla'})
    run.assert_not_called()


def test_failed_profile_restore_prevents_destructive_script(tmp_path, monkeypatch):
    monkeypatch.setattr(backend, 'default_home', lambda: tmp_path / 'state')
    journal = {'changed': True, 'profiles': [dict(index=3, category='Public')]}
    profiles.save(journal)
    monkeypatch.setattr(profiles, 'set_checked', Mock(side_effect=RuntimeError('adapter changed')))
    run = Mock()
    monkeypatch.setattr(wipe.subprocess, 'run', run)
    with pytest.raises(RuntimeError, match='adapter changed'):
        wipe.wipe_windows(root=tmp_path)
    run.assert_not_called()
    assert profiles.load() == journal


def test_wipe_holds_external_profile_lock_through_script(tmp_path, monkeypatch):
    home = tmp_path / 'system' / 'VLA'
    home.mkdir(parents=True)
    root = tmp_path / 'release'
    root.mkdir()
    (root / 'portable.flag').write_text('')
    monkeypatch.setattr(backend, 'default_home', lambda: home)
    def run(*args, **kwargs):
        assert kwargs['env'][wipe.ENV_PORTABLE] == str(root / 'LanTool-data')
        # The script must be able to remove VLA's data with the lock held.
        home.rmdir()
        return SimpleNamespace(returncode=0, stdout='{"issues":[],"reboot":false}')
    monkeypatch.setattr(wipe.subprocess, 'run', run)
    wipe.wipe_windows(root=root)
    assert (home.parent / 'vla-profile-records.lock').exists()


def test_pending_install_is_completed_before_ordinary_join(tmp_path, monkeypatch):
    order = []
    installer = SimpleNamespace(is_installed=lambda: True, installation_pending=lambda: True,
                                install=lambda *a: order.append('resume'),
                                start_service=lambda: order.append('start'))
    local = SimpleNamespace(status=lambda: {'address': 'abc'})
    tunnel = Tunnel(home=tmp_path, local=local, installer=installer)
    monkeypatch.setattr('silent_tunnel.tunnel.time.sleep', lambda _: None)
    tunnel.ensure_ready()
    assert order == ['resume', 'start']


def test_profile_transactions_merge_across_processes(tmp_path):
    script = r'''
import sys,time
from pathlib import Path
from silent_tunnel import backend, profile_records as p
home=Path(sys.argv[1]); index=int(sys.argv[2])
backend.default_home=lambda:home
def identity(i):
    time.sleep(.15)
    return dict(index=i,guid=str(i),profile_id=str(i),profile='LAN',category='Public')
p.identity=identity
p.set_checked=lambda *a:None
p.make_private([index])
'''
    home = tmp_path / 'VLA'
    workers = [subprocess.Popen([sys.executable, '-B', '-c', script, str(home), str(i)],
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
               for i in (4, 8)]
    for worker in workers:
        stdout, stderr = worker.communicate(timeout=20)
        assert worker.returncode == 0, stdout + stderr
    value = json.loads((home / 'prepare-private-record.json').read_text())
    assert {row['index'] for row in value['profiles']} == {4, 8}
