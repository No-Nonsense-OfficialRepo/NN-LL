"""Room actions prepare scoped firewall access without elevating the UI."""
import asyncio
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from lantool import launcher as core
from silent_tunnel import firewall


def owner():
    return SimpleNamespace(_firewall_ready=False, _firewall_lock=threading.Lock())


def test_development_python_never_gets_firewall_rules():
    state = owner()
    with patch.object(sys, 'frozen', False, create=True), patch.object(firewall, 'ensure_rules') as ensure:
        core.LauncherCore._prepare_firewall(state)
    ensure.assert_not_called()


def test_packaged_firewall_setup_is_serialized_and_cached():
    state = owner()
    entered, release = threading.Event(), threading.Event()
    def setup():
        entered.set()
        assert release.wait(2)
    with patch.object(sys, 'frozen', True, create=True), \
         patch.object(firewall, 'ensure_rules', side_effect=setup) as ensure, \
         ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(core.LauncherCore._prepare_firewall, state)
        assert entered.wait(2)
        second = pool.submit(core.LauncherCore._prepare_firewall, state)
        release.set()
        first.result(timeout=2)
        second.result(timeout=2)
    ensure.assert_called_once()
    assert state._firewall_ready


def test_declined_admin_permission_can_be_retried():
    state = owner()
    with patch.object(sys, 'frozen', True, create=True), \
         patch.object(firewall, 'ensure_rules', side_effect=[RuntimeError('permission declined'), None]) as ensure:
        with pytest.raises(RuntimeError, match='permission declined'):
            core.LauncherCore._prepare_firewall(state)
        assert not state._firewall_ready
        core.LauncherCore._prepare_firewall(state)
    assert state._firewall_ready
    assert ensure.call_count == 2


def test_firewall_setup_precedes_room_recovery_and_failure_stops_setup():
    state = SimpleNamespace(_network_session_recovered=False, role='host', tunnel=Mock(),
                            _prepare_firewall=Mock(side_effect=RuntimeError('denied')))
    with patch.object(core, 'AdapterSwitcher') as adapter:
        with pytest.raises(RuntimeError, match='denied'):
            core.LauncherCore._recover_network_session(state)
    adapter.assert_not_called()
    state.tunnel.recover.assert_not_called()
    assert not state._network_session_recovered


async def test_firewall_setup_precedes_discovery_listener():
    order = []
    tasks = []
    def submit(coro):
        task = asyncio.create_task(coro)
        tasks.append(task)
        return task
    async def listen(callback):
        order.append('listen')
        return Mock()
    state = SimpleNamespace(beacon_transport=None, _discovery_listening_since=None,
        runtime=SimpleNamespace(submit=submit), after=Mock(),
        pages={'room': SimpleNamespace(set_status=Mock())},
        _prepare_firewall=Mock(side_effect=lambda: order.append('firewall')),
        _beacon_seen=Mock(), _discovery_started=Mock(), _discovery_fallback=AsyncMock())
    with patch.object(core.BeaconListener, 'listen_discovered', side_effect=listen):
        core.LauncherCore._start_discovery(state)
        await tasks[0]
        await asyncio.sleep(0)
    assert order == ['firewall', 'listen']


@pytest.mark.parametrize('count,stale,repair', [('2', [], False), ('0', [], True), ('1', [], True),
                                                ('2', ['LAN Old Build'], True)])
def test_only_missing_or_inactive_allow_rules_need_admin(count, stale, repair):
    with patch.object(firewall.subprocess, 'run', return_value=Mock(returncode=0, stdout=count)) as run, \
         patch.object(firewall, 'stale_rule_names', return_value=stale), \
         patch.object(firewall, 'configure_rules') as configure:
        firewall.ensure_rules()
    assert configure.called is repair
    command = run.call_args.args[0][-1]
    assert "Direction -eq 'Inbound'" in command
    assert "Action -eq 'Allow'" in command


def test_firewall_changes_use_existing_narrow_admin_action():
    with patch('silent_tunnel.admin_actions.run_elevated') as elevated:
        firewall.configure_rules()
    elevated.assert_called_once_with('launcher_firewall')
