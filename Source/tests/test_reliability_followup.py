import asyncio
import json
import pytest
from silent_tunnel.store import State, save_obj, load_state
from lantool.filesync.index import validate_index
from lantool.filesync.server import FileSyncServer
from lantool.trust.signing import generate_keypair


def test_state_backup_recovers(tmp_path):
    path = tmp_path / 'state.json'
    save_obj(path, State(joined=['room']))
    path.write_text('{broken')
    assert load_state(path).joined == ['room']
    path.with_suffix('.json.bak').write_text('{broken')
    with pytest.raises(OSError):
        load_state(path)


@pytest.mark.parametrize('paths', [('data', 'data/file'), ('DATA/file', 'data')])
def test_index_directory_conflict(paths):
    entries = [{'path': p, 'size': 0, 'sha256': '0' * 64} for p in paths]
    with pytest.raises(ValueError, match='conflicts'):
        validate_index({'game_id': 'game', 'files': entries}, 'game')


def test_art_read_is_bounded(tmp_path):
    # Oversized input must be rejected without loading the complete file.
    async def run():
        priv, _ = generate_keypair()
        art = tmp_path / 'art.png'
        with art.open('wb') as stream:
            stream.truncate(32 * 1024 * 1024)
        server = FileSyncServer(priv, tmp_path, library_provider=lambda: {
            'game': {'_art_path': str(art), 'art_sha256': '0' * 64}})
        replies = []
        async def reply(writer, code, *args):
            replies.append(code)
        server._reply = reply
        await server._art(None, 'game/portrait')
        assert replies == [404]
    asyncio.run(run())


@pytest.mark.asyncio
async def test_slow_header_deadline_releases_connection(tmp_path, monkeypatch):
    import lantool.filesync.server as module
    monkeypatch.setattr(module, 'HEADER_TIMEOUT', .05)
    private, _ = generate_keypair()
    server = FileSyncServer(private, tmp_path, host='127.0.0.1', port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        writer.write(b'GET /library HTTP/1.0\r\nX: value\r\n')
        await writer.drain()
        assert await asyncio.wait_for(reader.read(), 1) == b''
        await asyncio.sleep(0)
        assert not server._connections_by_ip
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_library_cache_invalidates_on_executable_change(tmp_path, monkeypatch):
    import lantool.install_manifest as receipts
    private, _ = generate_keypair()
    exe = tmp_path / 'game.exe'
    exe.write_bytes(b'one')
    manifest = {'id': 'game', 'exe': 'game.exe', '_game_dir': str(tmp_path)}
    server = FileSyncServer(private, tmp_path, library_provider=lambda: {'game': manifest})
    original = receipts.executable_record
    calls = []
    def record(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(receipts, 'executable_record', record)
    async def reply(*args):
        pass
    server._reply = reply
    await asyncio.gather(server._library(None), server._library(None))
    assert len(calls) == 1
    exe.write_bytes(b'changed')
    await server._library(None)
    assert len(calls) == 2
