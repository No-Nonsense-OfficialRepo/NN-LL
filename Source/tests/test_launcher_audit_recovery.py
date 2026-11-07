import asyncio
import base64
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from lantool import launcher as core
from lantool.netcore.controller import RoomController, State
from lantool.trust import signing
from lantool.trust.planet_transport import fetch_planet
from tests.test_close_timeout import _core, _Service


@pytest.mark.parametrize('truncated', [False, True])
async def test_fragmented_moon_response_and_truncated_body(tmp_path, truncated):
    private, public = signing.generate_keypair()
    data = b'moon' * 1000
    body = json.dumps({**signing.sign_planet(private, data),
                       'data': base64.b64encode(data).decode()}).encode()
    async def serve(reader, writer):
        try:
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.0 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n')
            await writer.drain()
            await asyncio.sleep(.02)
            writer.write(body[:20] if truncated else body[:100])
            await writer.drain()
            if not truncated:
                await asyncio.sleep(.02)
                writer.write(body[100:])
                await writer.drain()
        finally:
            writer.close()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    destination = tmp_path / 'moon'
    destination.write_bytes(b'old')
    try:
        result = await fetch_planet('127.0.0.1', server.sockets[0].getsockname()[1], public,
                                    signing.sha256_hex(data), destination)
        assert result is not truncated
        assert destination.read_bytes() == (b'old' if truncated else data)
    finally:
        server.close()
        await server.wait_closed()


async def test_adapter_restore_failure_still_leaves_network():
    network = SimpleNamespace(leave=AsyncMock())
    adapter = SimpleNamespace(restore=MagicMock(side_effect=PermissionError('denied')))
    controller = RoomController(network, adapter, None, None, None, None)
    controller.net_id = 'room'
    controller.state = State.ZEROTIER
    with pytest.raises(RuntimeError, match='denied'):
        await controller.leave()
    network.leave.assert_awaited_once_with('room')
    assert controller.state == State.ETHERNET


def test_settings_failure_does_not_prevent_shutdown():
    runtime = core.AsyncLoopThread()
    try:
        server = _Service()
        fake = _core(runtime, file_sync_server=server)
        with patch.object(core, '_write_config', side_effect=OSError('full')), \
                patch.object(core, '_other_launcher_running', return_value=False), \
                patch.object(core, '_same_role_launcher_running', return_value=False):
            core.LauncherCore.close(fake)
            deadline = time.monotonic() + 5
            while not server.stopped and time.monotonic() < deadline:
                time.sleep(.01)
        assert server.stopped
        assert any(delay == int(core.CLOSE_DEADLINE * 1000) for delay, _ in fake.scheduled)
    finally:
        runtime.stop()


def test_leave_stops_other_services_after_controller_failure():
    runtime = core.AsyncLoopThread()
    stopped = []
    fake = SimpleNamespace(discovery_task=None, library_refresh_task=None, beacon_transport=None,
                           host_conflict_transport=None, process_watcher=None, room_admission=None,
                           room_controller=SimpleNamespace(leave=AsyncMock(side_effect=OSError('denied'))),
                           peer_file_server=_Service(), presence_client=_Service(), presence_server=None,
                           host_room=None, file_sync_server=_Service(), runtime=runtime)
    services = [fake.peer_file_server, fake.presence_client, fake.file_sync_server]
    fake._cancel_sync = lambda: None
    fake._stop_file_sync_prewarm = AsyncMock()
    fake._log_room_error = lambda error: None
    fake._leave_network = stopped.append
    fake._run_background = lambda function, callback, label: callback(function())
    try:
        core.LauncherCore.leave_room(fake, timeout=2)
        assert all(service.stopped for service in services)
        assert stopped and 'denied' in str(stopped[0])
    finally:
        runtime.stop()


def test_failed_adapter_restore_does_not_skip_tunnel_leave():
    fake = SimpleNamespace(role='client', tunnel=SimpleNamespace(leave=MagicMock()),
                           _log_room_error=lambda error: None)
    completed = []
    fake._room_left = lambda result, error: completed.append(error)
    fake._run_background = lambda function, callback, label: callback(function())
    with patch.object(core, 'AdapterSwitcher') as switcher:
        switcher.return_value.restore.side_effect = OSError('denied')
        core.LauncherCore._leave_network(fake)
    fake.tunnel.leave.assert_called_once()
    assert completed and 'denied' in str(completed[0])


async def test_installed_game_seeding_uses_protected_access_and_endpoint_fallback(tmp_path):
    app = object.__new__(core.LauncherCore)
    app.trusted_host_pub = 'key'
    app.room = SimpleNamespace(network_id='room')
    app.room_access = object()
    app.library = {'game': {'id': 'game', 'install_dir': str(tmp_path)}}
    app.syncing_game = False
    app.peer_file_server = MagicMock()
    app.presence_client = SimpleNamespace(publish_seeds=AsyncMock())
    app.seeded_games, app.seeded_files = set(), {}
    beacon = {'host_pub': 'key', 'net_id': 'room', 'host': 'physical', 'host_zt': 'overlay'}
    fetch = AsyncMock(side_effect=[OSError('not reachable'), []])
    with patch('lantool.filesync.client.fetch_index', fetch):
        await app._seed_existing_games(beacon)
    assert [call.args[0] for call in fetch.await_args_list] == ['physical', 'overlay']
    assert all(call.kwargs['access'] is app.room_access for call in fetch.await_args_list)
