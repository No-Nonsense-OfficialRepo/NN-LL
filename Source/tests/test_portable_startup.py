"""Normal UI startup is unprivileged; Windows mutations stay in narrow helpers."""
import json
import runpy
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest
from lantool import launcher as core
from lantool.netcore import adapter
from silent_tunnel.admin_actions import _run_action


def test_entry_point_does_not_elevate_the_ui():
    entry = Path(__file__).resolve().parents[1] / 'run_launcher.py'
    main = Mock(return_value=0)
    with patch.dict(sys.modules, {'lantool.qt.main': SimpleNamespace(main=main)}), \
         patch.object(sys, 'argv', [str(entry)]), \
         patch('lantool.single_instance.already_running', return_value=False), \
         patch('ctypes.windll.shell32.IsUserAnAdmin') as admin, \
         patch('ctypes.windll.shell32.ShellExecuteW') as elevate:
        with pytest.raises(SystemExit) as exit_info:
            runpy.run_path(str(entry), run_name='__main__')
    assert exit_info.value.code == 0
    main.assert_called_once()
    admin.assert_not_called()
    elevate.assert_not_called()


@pytest.mark.parametrize('role', ['host', 'client'])
def test_opening_ui_does_not_start_or_modify_networking(role):
    owner = SimpleNamespace(_closing=False, role=role,
                            pages={'room': SimpleNamespace(set_status=Mock())})
    with patch.object(core, 'AdapterSwitcher') as switcher, \
         patch('silent_tunnel.firewall.ensure_rules') as firewall:
        core.LauncherCore._recover(owner)
    switcher.assert_not_called()
    firewall.assert_not_called()
    owner.pages['room'].set_status.assert_called_once()


def test_recovery_skipped_for_other_role_runs_once_that_role_exits():
    owner = SimpleNamespace(_network_session_recovered=False, role='client', tunnel=Mock(),
                            _prepare_firewall=Mock())
    with patch.object(core, '_other_launcher_running', return_value=True), \
         patch.object(core, 'AdapterSwitcher') as switcher:
        core.LauncherCore._recover_network_session(owner)
    switcher.assert_not_called()
    owner.tunnel.recover.assert_not_called()
    assert not owner._network_session_recovered  # skipped, so it is not recorded as recovered (audit A09)
    assert owner._network_session_requested  # but close() still knows the network was used
    with patch.object(core, '_other_launcher_running', return_value=False), \
         patch.object(core, 'AdapterSwitcher') as switcher:
        core.LauncherCore._recover_network_session(owner)
    switcher.return_value.recover_after_crash.assert_called_once()
    owner.tunnel.recover.assert_called_once()
    assert owner._network_session_recovered
    with patch.object(core, '_other_launcher_running') as peer:
        core.LauncherCore._recover_network_session(owner)
    peer.assert_not_called()


def test_requested_network_recovery_retries_after_failure():
    owner = SimpleNamespace(_network_session_recovered=False, role='host', tunnel=Mock(),
                            _prepare_firewall=Mock())
    with patch.object(core, '_other_launcher_running', return_value=False), \
         patch.object(core, 'AdapterSwitcher') as switcher:
        switcher.return_value.recover_after_crash.side_effect = RuntimeError('denied')
        with pytest.raises(RuntimeError):
            core.LauncherCore._recover_network_session(owner)
        assert not owner._network_session_recovered
        switcher.return_value.recover_after_crash.side_effect = None
        core.LauncherCore._recover_network_session(owner)
    owner.tunnel.recover.assert_called_once()
    assert owner._network_session_recovered


def test_adapter_preference_uses_structured_elevation(tmp_path):
    details = dict(InterfaceIndex=43, InterfaceAlias='VLA [room]', InterfaceMetric=35)
    with patch.object(adapter, '_ps', return_value=json.dumps(details)) as read, \
         patch('silent_tunnel.admin_actions.run_elevated') as elevated:
        adapter.AdapterSwitcher(tmp_path / 'state.json', run=read).prefer_zerotier('VLA [room]')
    assert read.call_count == 1
    elevated.assert_called_once_with('adapter_metric', interface_index=43,
                                     alias='VLA [room]', metric=5)


@pytest.mark.parametrize('index,alias,metric', [
    ('43; calc', 'VLA', 5), (True, 'VLA', 5), (-1, 'VLA', 5),
    (43, '', 5), (43, 'VLA', '5; calc'), (43, 'VLA', -1), (43, 'VLA', 10000)])
def test_admin_adapter_operation_rejects_unstructured_inputs(index, alias, metric):
    with patch.object(adapter, '_ps') as run:
        with pytest.raises(ValueError):
            _run_action(dict(action='adapter_metric', interface_index=index, alias=alias, metric=metric))
    run.assert_not_called()


def test_admin_adapter_operation_revalidates_ownership_and_ipv4():
    with patch.object(adapter, '_ps') as run:
        _run_action(dict(action='adapter_metric', interface_index=43,
                         alias="VLA's room", metric=5))
    command = run.call_args.args[0]
    assert 'Test-VlaAdapter $device' in command
    assert '-AddressFamily IPv4' in command
    assert "$iface.InterfaceAlias -eq 'VLA''s room'" in command
    assert '$iface | Set-NetIPInterface -InterfaceMetric 5 -ErrorAction Stop' in command


def test_adapter_already_preferred_does_not_request_elevation(tmp_path):
    details = dict(InterfaceIndex=43, InterfaceAlias='VLA [room]', InterfaceMetric=5)
    with patch.object(adapter, '_ps', return_value=json.dumps(details)) as read, \
         patch('silent_tunnel.admin_actions.run_elevated') as elevated:
        adapter.AdapterSwitcher(tmp_path / 'state.json', run=read).prefer_zerotier('VLA [room]')
    elevated.assert_not_called()
    assert not (tmp_path / 'state.json').exists()


def test_restore_uses_helper_and_keeps_state_if_permission_is_denied(tmp_path):
    path = tmp_path / 'state.json'
    state = dict(active=True, interface_index=43, alias='VLA [room]', old_metric=35)
    path.write_text(json.dumps(state))
    with patch.object(adapter, '_ps') as read, \
         patch('silent_tunnel.admin_actions.run_elevated', side_effect=RuntimeError('denied')) as elevated:
        switcher = adapter.AdapterSwitcher(path, run=read)
        with pytest.raises(RuntimeError):
            switcher.restore()
        assert json.loads(path.read_text())['active']
        elevated.side_effect = None
        switcher.restore()
    assert not json.loads(path.read_text())['active']
    elevated.assert_called_with('adapter_metric', interface_index=43,
                                alias='VLA [room]', metric=35, missing_ok=True)
