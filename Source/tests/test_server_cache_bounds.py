import asyncio
import hashlib
import os

from lantool.filesync import server as module
from lantool.trust.signing import generate_keypair


def make_server(tmp_path, count=3):
    for number in range(count):
        folder = tmp_path / str(number)
        folder.mkdir()
        (folder / 'game.bin').write_bytes(b'payload')
    private, _ = generate_keypair()
    return module.FileSyncServer(private, tmp_path, host='127.0.0.1', port=0)


async def test_snapshot_eviction_rebuilds_and_releases_idle_locks(tmp_path, monkeypatch):
    server = make_server(tmp_path)
    monkeypatch.setattr(module, 'SNAPSHOT_LIMIT', 2)
    await server.signed_index('0')
    await server.signed_index('1')
    await server.signed_index('0')
    await server.signed_index('2')
    assert list(server._index_snapshots) == ['0', '2']
    assert not server._index_locks
    rebuilt = await server.signed_index('1')
    assert rebuilt['files'][0]['size'] == 7


async def test_oversized_index_not_retained(tmp_path, monkeypatch):
    server = make_server(tmp_path, 1)
    monkeypatch.setattr(module, 'SNAPSHOT_BYTES_LIMIT', 1)
    assert (await server.signed_index('0'))['files']
    assert not server._index_snapshots


async def test_expired_snapshot_rechecks_tree(tmp_path, monkeypatch):
    server = make_server(tmp_path, 1)
    await server.signed_index('0')
    path = tmp_path / '0' / 'game.bin'
    stat = path.stat()
    path.write_bytes(b'changed')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    server._snapshot_times['0'] -= module.SNAPSHOT_MAX_AGE + 1
    calls = []
    real_build = module.build_index
    def build(*args, **kwargs):
        calls.append(True)
        return real_build(*args, **kwargs)
    monkeypatch.setattr(module, 'build_index', build)
    result = await server.signed_index('0')
    assert calls == [True]
    assert result['files'][0]['sha256'] == hashlib.sha256(b'changed').hexdigest()


async def test_removed_games_release_snapshots_and_finished_jobs(tmp_path):
    server = make_server(tmp_path, 1)
    job = server._start_index_job('0')
    await job['task']
    (tmp_path / '0' / 'game.bin').unlink()
    (tmp_path / '0').rmdir()
    assert await server.index_status() == {}
    assert not server._index_jobs and not server._current_index_jobs


async def test_upload_counter_counts_bytes_delivered(tmp_path):
    server = make_server(tmp_path, 1)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
        writer.write(b'GET /file/0/game.bin HTTP/1.0\r\n\r\n')
        await writer.drain()
        response = await reader.read()
        assert response.endswith(b'payload')
        assert server.bytes_sent == 7
        writer.close()
        await writer.wait_closed()
    finally:
        await server.stop()
