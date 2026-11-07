"""Real loopback TLS handoff tests; no installed files or VLA are touched."""
import asyncio
import hashlib
import json
from pathlib import Path
import secrets
import time
import zipfile
from unittest.mock import Mock
import pytest
from lantool._version import __version__
from lantool.netcore.launcher_share import LauncherShare, exchange, download, build_package


def test_update_endpoint_is_bound_to_signed_announcement():
    from lantool.trust.signing import generate_keypair
    from lantool.netcore.beacon import make_beacon, parse_beacon
    private, public = generate_keypair()
    meta = dict(protocol=1, port=47808, fingerprint='1'*64, host='192.168.1.5')
    raw = make_beacon(private, 'abcdef0123456789', '192.168.1.5', 47800, 'hash', __version__,
                      host_pub=public, launcher_share=meta)
    assert parse_beacon(raw, public)['launcher_share'] == meta
    altered = json.loads(raw)
    altered['launcher_share']['fingerprint'] = '2'*64
    assert parse_beacon(json.dumps(altered).encode(), public) is None
    invalid = make_beacon(private, 'abcdef0123456789', '192.168.1.5', 47800, 'hash', __version__,
                          host_pub=public, launcher_share={**meta, 'port': '../bad'})
    assert parse_beacon(invalid, public) is None


async def setup_share(tmp_path):
    path = tmp_path / 'release.zip'
    path.write_bytes(secrets.token_bytes(800000))
    factory = Mock(return_value=path)
    server = LauncherShare(factory, host='127.0.0.1', port=0)
    await server.start()
    beacon = dict(host='127.0.0.1', version=__version__, launcher_share=server.metadata)
    return server, beacon, factory, path


async def ask(beacon):
    secret = secrets.token_hex(32)
    result = await exchange(beacon, dict(action='request', secret=secret, name='Player One'))
    assert result['status'] == 'pending'
    return dict(id=result['id'], secret=secret)


@pytest.mark.asyncio
async def test_nothing_transfers_before_host_approval_and_correct_key(tmp_path):
    server, beacon, factory, package = await setup_share(tmp_path)
    try:
        client = await ask(beacon)
        assert (await exchange(beacon, dict(client, action='download')))['status'] == 'denied'
        assert (await exchange(beacon, dict(client, action='unlock', pin='000')))['status'] == 'denied'
        factory.assert_not_called()
        await server.decide(client['id'], True)
        pin = server.snapshot()[0]['pin']
        assert len(pin) == 3 and pin.isdigit()
        assert 'pin' not in await exchange(beacon, dict(client, action='poll'))
        wrong = '001' if pin == '000' else '000'
        assert (await exchange(beacon, dict(client, action='unlock', pin=wrong)))['status'] == 'wrong_pin'
        assert (await exchange(beacon, dict(client, action='download')))['status'] == 'denied'
        ready = await exchange(beacon, dict(client, action='unlock', pin=pin))
        client['token'] = ready['token']
        assert (await exchange(beacon, dict(client, action='download', token='wrong')))['status'] == 'denied'
        destination = tmp_path / 'received.zip'
        await download(beacon, client, destination)
        assert destination.read_bytes() == package.read_bytes()
        assert not list(tmp_path.glob('*.part'))
        assert (await exchange(beacon, dict(client, action='download')))['status'] == 'denied'
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_three_wrong_keys_revoke_request_even_if_next_key_is_correct(tmp_path):
    server, beacon, _, _ = await setup_share(tmp_path)
    try:
        client = await ask(beacon)
        await server.decide(client['id'], True)
        pin = server.snapshot()[0]['pin']
        wrong = '999' if pin != '999' else '998'
        for expected in ('wrong_pin','wrong_pin','denied'):
            assert (await exchange(beacon, dict(client, action='unlock', pin=wrong)))['status'] == expected
        assert (await exchange(beacon, dict(client, action='unlock', pin=pin)))['status'] == 'denied'
        assert server.snapshot() == []
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_denial_expiry_client_cancel_and_wrong_session_cannot_download(tmp_path):
    server, beacon, _, _ = await setup_share(tmp_path)
    try:
        client = await ask(beacon)
        assert (await exchange(beacon, dict(client, action='poll', secret=secrets.token_hex(32))))['status'] == 'expired'
        await server.decide(client['id'], False)
        assert (await exchange(beacon, dict(client, action='download')))['status'] == 'denied'
        client = await ask(beacon)
        server.requests[client['id']]['expires'] = time.monotonic()-1
        assert (await exchange(beacon, dict(client, action='poll')))['status'] == 'expired'
        client = await ask(beacon)
        assert (await exchange(beacon, dict(client, action='cancel')))['status'] == 'cancelled'
        assert (await exchange(beacon, dict(client, action='download')))['status'] == 'expired'
        assert (await exchange(beacon, dict(action='request', secret=secrets.token_hex(32))))['status'] == 'rate_limited'
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_certificate_tampering_and_corrupt_download_leave_no_file(tmp_path):
    server, beacon, _, package = await setup_share(tmp_path)
    try:
        bad = {**beacon, 'launcher_share': {**server.metadata, 'fingerprint': '0'*64}}
        with pytest.raises(OSError, match='certificate'):
            await ask(bad)
        client = await ask(beacon)
        await server.decide(client['id'], True)
        ready = await exchange(beacon, dict(client, action='unlock', pin=server.snapshot()[0]['pin']))
        client['token'] = ready['token']
        package.write_bytes(b'changed')
        destination = tmp_path / 'received.zip'
        with pytest.raises(OSError):
            await download(beacon, client, destination)
        assert not destination.exists()
        assert not list(tmp_path.glob('*.part'))
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_client_cancellation_leaves_no_partial_or_complete_package(tmp_path):
    server, beacon, _, _ = await setup_share(tmp_path)
    try:
        client = await ask(beacon)
        await server.decide(client['id'], True)
        ready = await exchange(beacon, dict(client, action='unlock', pin=server.snapshot()[0]['pin']))
        client['token'] = ready['token']
        task = asyncio.current_task()
        destination = tmp_path / 'received.zip'
        with pytest.raises(asyncio.CancelledError):
            await download(beacon, client, destination, lambda *_: task.cancel())
        assert not destination.exists()
        assert not list(tmp_path.glob('*.part'))
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_host_close_revokes_pending_and_authorized_requests(tmp_path):
    server, beacon, _, _ = await setup_share(tmp_path)
    client = await ask(beacon)
    await server.decide(client['id'], True)
    await server.stop()
    assert server.requests == {}
    with pytest.raises(OSError):
        await exchange(beacon, dict(client, action='download'))


@pytest.mark.asyncio
async def test_host_close_aborts_an_idle_tls_client_without_waiting_for_a_request(tmp_path):
    from lantool.netcore.admission import AdmissionAccess
    server, _, _, _ = await setup_share(tmp_path)
    reader, writer = await AdmissionAccess(server.metadata['fingerprint']).connect('127.0.0.1', server.port)
    await asyncio.sleep(0)
    try:
        await asyncio.wait_for(server.stop(), 1)
        assert await asyncio.wait_for(reader.read(), 1) == b''
    finally:
        writer.close()


def test_export_contains_only_release_files_and_rejects_changed_installs(tmp_path):
    root = tmp_path / 'installed'
    release = root / 'Launcher Bin/Release'
    release.mkdir(parents=True)
    (release / 'version.json').write_text(json.dumps({'version': __version__}))
    files = ['Host.exe','Client.exe','Quick Start.exe','LICENSE','Launcher Bin/runtime.dll']
    lines = []
    for name in files:
        data = name.encode()
        (root / name).write_bytes(data)
        lines.append(hashlib.sha256(data).hexdigest()+' *'+name)
    (release / 'SHA256SUMS.txt').write_text('\n'.join(lines))
    (root / 'Game Directory').mkdir()
    (root / 'Game Directory/private-game.exe').write_bytes(b'game')
    (root / 'LanTool-data').mkdir()
    (root / 'LanTool-data/launcher.json').write_text('private profile')
    destination = tmp_path / 'shared.zip'
    build_package(root, destination)
    with zipfile.ZipFile(destination) as archive:
        assert set(archive.namelist()) == set(files) | {'Launcher Bin/Release/version.json','Launcher Bin/Release/SHA256SUMS.txt','Game Directory/'}
    (root / 'Client.exe').write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        build_package(root, tmp_path/'bad.zip')


def test_export_reads_bom_release_metadata(tmp_path):
    root = tmp_path / 'installed'
    release = root / 'Launcher Bin/Release'
    release.mkdir(parents=True)
    (release / 'version.json').write_text(json.dumps({'version': __version__}), encoding='utf-8-sig')
    files = ['Host.exe', 'Client.exe', 'Quick Start.exe']
    for name in files:
        (root / name).write_bytes(name.encode())
    (release / 'SHA256SUMS.txt').write_text('\n'.join(
        hashlib.sha256(name.encode()).hexdigest() + ' *' + name for name in files))
    destination = tmp_path / 'shared.zip'
    build_package(root, destination)
    with zipfile.ZipFile(destination) as archive:
        assert set(files).issubset(archive.namelist())


@pytest.mark.asyncio
async def test_delayed_host_reply_still_creates_approval_request(tmp_path, monkeypatch):
    import lantool.netcore.launcher_share as sharing
    server, beacon, _, _ = await setup_share(tmp_path)
    original = sharing._send_message

    async def delayed_reply(writer, message, timeout=sharing.CONTROL_TIMEOUT):
        if message.get('status') == 'pending':
            await asyncio.sleep(5.2)  # Exceeds the former five-second control reply deadline.
        return await original(writer, message, timeout)

    monkeypatch.setattr(sharing, '_send_message', delayed_reply)
    try:
        client = await ask(beacon)
        assert client['id'] in server.requests
        assert server.snapshot()[0]['status'] == 'pending'
    finally:
        await server.stop()
