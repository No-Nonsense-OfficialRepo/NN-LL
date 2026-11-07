"""Host indexing stays observable, shared, durable, and safe when files change."""
import asyncio
import hashlib
import os
import time
import threading
import pytest

from lantool.filesync.client import fetch_index
from lantool.filesync.index import HashCache, SqliteHashCache, build_index
from lantool.filesync.server import FileSyncServer
from lantool.trust.signing import generate_keypair


async def test_clients_share_one_index_job_and_receive_progress(tmp_path, monkeypatch):
    from lantool.filesync import server as module
    root = tmp_path / 'games'
    game = root / 'sample'
    game.mkdir(parents=True)
    (game / 'data.bin').write_bytes(b'a' * 100)
    private, public = generate_keypair()
    server = FileSyncServer(private, root, host='127.0.0.1', port=0)
    real_build = module.build_index
    calls = []
    def slow_build(*args, **kwargs):
        calls.append(1)
        time.sleep(.25)
        return real_build(*args, **kwargs)
    monkeypatch.setattr(module, 'build_index', slow_build)
    await server.start()
    try:
        progress = []
        first = asyncio.create_task(fetch_index('127.0.0.1', server.port, public, 'sample',
                                                on_progress=progress.append))
        second = asyncio.create_task(fetch_index('127.0.0.1', server.port, public, 'sample'))
        a, b = await asyncio.gather(first, second)
        assert a == b and a[0]['path'] == 'data.bin'
        assert calls == [1]
        assert any(item['state'] == 'running' and item['id'] for item in progress)
    finally:
        await server.stop()


def test_sqlite_cache_survives_interrupted_scan(tmp_path):
    root = tmp_path / 'game'
    root.mkdir()
    path = root / 'data.bin'
    path.write_bytes(b'abc' * 100)
    db = tmp_path / 'host-index.sqlite3'
    first = SqliteHashCache(db)
    expected = first.hashes_with_pieces(str(path), path)
    first.close()
    reopened = SqliteHashCache(db)
    try:
        sha, pieces, cached = reopened.hashes_with_pieces(str(path), path)
        assert cached and (sha, pieces) == expected[:2]
    finally:
        reopened.close()


def test_damaged_sqlite_cache_is_rebuilt(tmp_path):
    db = tmp_path / 'host-index.sqlite3'
    db.write_bytes(b'not a database')
    cache = SqliteHashCache(db)
    try:
        assert list(tmp_path.glob('host-index.sqlite3.corrupt-*'))
        root = tmp_path / 'game'
        root.mkdir()
        (root / 'data.bin').write_bytes(b'healthy')
        assert build_index('game', root, cache)['files'][0]['size'] == 7
    finally:
        cache.close()


def test_changed_file_is_reindexed_before_publishing(tmp_path):
    root = tmp_path / 'game'
    root.mkdir()
    file = root / 'data.bin'
    file.write_bytes(b'first')
    class ChangingCache(HashCache):
        changed = False
        def hashes_with_pieces(self, key, path, **kwargs):
            result = super().hashes_with_pieces(key, path, **kwargs)
            if not self.changed:
                self.changed = True
                file.write_bytes(b'second version')
            return result
    index = build_index('game', root, ChangingCache())
    assert index['files'][0]['size'] == len(b'second version')
    assert index['files'][0]['sha256'] == hashlib.sha256(b'second version').hexdigest()


async def test_manual_recheck_detects_same_size_same_timestamp_edit(tmp_path):
    root = tmp_path / 'games'
    game = root / 'sample'
    game.mkdir(parents=True)
    file = game / 'data.bin'
    file.write_bytes(b'AAAA')
    private, _ = generate_keypair()
    server = FileSyncServer(private, root, host='127.0.0.1', port=0,
                            cache_path=tmp_path / 'host.sqlite3')
    await server.start()
    try:
        first = await server.signed_index('sample')
        stat = file.stat()
        file.write_bytes(b'BBBB')
        os.utime(file, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        cached = await server.signed_index('sample')
        assert cached['files'][0]['sha256'] == first['files'][0]['sha256']
        checked = await server.recheck_index('sample')
        assert checked['files'][0]['sha256'] != first['files'][0]['sha256']
        status = await server.index_status()
        assert status['sample']['state'] == 'ready'
        assert status['sample']['done'] == status['sample']['total']
    finally:
        await server.stop()


async def test_host_index_error_reaches_client_without_long_timeout(tmp_path, monkeypatch):
    from lantool.filesync import server as module
    root = tmp_path / 'games'
    (root / 'sample').mkdir(parents=True)
    private, public = generate_keypair()
    server = FileSyncServer(private, root, host='127.0.0.1', port=0)
    def fail(*args, **kwargs):
        raise OSError('game disk unavailable')
    monkeypatch.setattr(module, 'build_index', fail)
    await server.start()
    try:
        with pytest.raises(Exception, match='game disk unavailable'):
            await asyncio.wait_for(fetch_index('127.0.0.1', server.port, public, 'sample'), 5)
    finally:
        await server.stop()


async def test_stopping_host_cancels_active_index_worker(tmp_path, monkeypatch):
    from lantool.filesync import server as module
    root = tmp_path / 'games'
    (root / 'sample').mkdir(parents=True)
    private, _ = generate_keypair()
    server = FileSyncServer(private, root, host='127.0.0.1', port=0)
    entered = threading.Event()
    def wait_for_stop(*args, cancelled=None, **kwargs):
        entered.set()
        while not cancelled():
            time.sleep(.01)
        return {}
    monkeypatch.setattr(module, 'build_index', wait_for_stop)
    await server.start()
    server._start_index_job('sample')
    assert await asyncio.to_thread(entered.wait, 2)
    await asyncio.wait_for(server.stop(), 3)
