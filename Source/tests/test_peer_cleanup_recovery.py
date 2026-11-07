import asyncio
import json
import threading
from pathlib import Path

import pytest

from lantool.filesync import client
from lantool.filesync import peer as module
from lantool.filesync.server import FileSyncServer
from lantool.trust.signing import generate_keypair


async def test_evicted_job_restarts_token_and_fetches_verified_index(tmp_path, monkeypatch):
    private, public = generate_keypair()
    game = tmp_path / 'game'
    game.mkdir()
    (game / 'data.bin').write_bytes(b'payload')
    host = FileSyncServer(private, tmp_path)
    signed = await host.signed_index('game')
    responses = [(202, {'id': 'a' * 32, 'state': 'running'}), (404, None), (200, signed)]
    routes = []
    class Writer:
        def close(self): pass
    async def request(host, port, route, *args, **kwargs):
        routes.append(route)
        status, obj = responses.pop(0)
        body = json.dumps(obj).encode() if obj else b''
        reader = asyncio.StreamReader()
        reader.feed_data(body)
        reader.feed_eof()
        return status, {'content-length': str(len(body))}, reader, Writer()
    monkeypatch.setattr(client, '_request', request)
    files = await client.fetch_index('mock', 1, public, 'game')
    assert files[0]['size'] == 7
    assert '?job=' in routes[1] and '?job=' not in routes[2]


async def test_repeated_job_evictions_are_bounded(monkeypatch):
    calls = []
    class Writer:
        def close(self): pass
    async def request(*args, **kwargs):
        calls.append(True)
        status = 202 if len(calls) % 2 else 404
        body = json.dumps({'id': 'a' * 32, 'state': 'running'}).encode() if status == 202 else b''
        reader = asyncio.StreamReader()
        reader.feed_data(body)
        reader.feed_eof()
        return status, {'content-length': str(len(body))}, reader, Writer()
    monkeypatch.setattr(client, '_request', request)
    with pytest.raises(client._HttpError, match='repeatedly expired'):
        await client.fetch_index('mock', 1, 'unused', 'game')
    assert len(calls) == 8


@pytest.mark.parametrize('operation', ['stop', 'pause_and_drain'])
async def test_peer_cleanup_waits_for_actual_disk_reader(tmp_path, monkeypatch, operation):
    path = tmp_path / 'game' / 'data.bin'
    path.parent.mkdir()
    path.write_bytes(b'payload')
    peer = module.PeerFileServer(tmp_path, host='127.0.0.1', port=0)
    peer.set_shared_files({'game': ['data.bin']})
    entered, release, closed = threading.Event(), threading.Event(), threading.Event()
    real_open = Path.open
    class SlowReader:
        def __enter__(self): return self
        def __exit__(self, *args): closed.set()
        def seek(self, offset): pass
        def read(self, length):
            entered.set()
            if not release.wait(5): raise RuntimeError('test reader was not released')
            return b'payload'
    def open_file(current, *args, **kwargs):
        return SlowReader() if current == path else real_open(current, *args, **kwargs)
    monkeypatch.setattr(Path, 'open', open_file)
    await peer.start()
    reader, writer = await asyncio.open_connection('127.0.0.1', peer.port)
    writer.write(b'GET /piece/game/data.bin HTTP/1.0\r\nRange: bytes=0-6\r\n\r\n')
    await writer.drain()
    cleanup = None
    try:
        assert await asyncio.to_thread(entered.wait, 3)
        cleanup = asyncio.create_task(getattr(peer, operation)())
        await asyncio.sleep(.05)
        assert not cleanup.done() and not closed.is_set()
        release.set()
        await asyncio.wait_for(cleanup, 3)
        assert closed.is_set() and not peer._handlers
    finally:
        release.set()
        if cleanup: await asyncio.gather(cleanup, return_exceptions=True)
        writer.close()
        await peer.stop()


def test_peer_indexes_pruned_on_unshare_and_bounded(tmp_path, monkeypatch):
    peer = module.PeerFileServer(tmp_path)
    monkeypatch.setattr(module, 'PEER_INDEX_LIMIT', 2)
    entry = {'path': 'data.bin', 'size': 1, 'pieces': ['a' * 64]}
    peer.register_index('first', tmp_path, [entry])
    peer.set_shared_files({'first': ['data.bin']})
    peer.register_index('second', tmp_path, [entry])
    peer.register_index('third', tmp_path, [entry])
    assert set(peer.indexes) == {'second', 'third'}
    assert 'first' not in peer.shared_games
    peer.set_shared_files({'first': ['data.bin'], 'second': ['data.bin']})
    assert peer.shared_games == {'second'}
    peer.set_shared_files({})
    assert 'second' not in peer.indexes and 'second' not in peer.roots


def test_oversized_peer_index_is_not_advertised(tmp_path, monkeypatch):
    peer = module.PeerFileServer(tmp_path)
    monkeypatch.setattr(module, 'PEER_INDEX_BYTES', 1)
    peer.register_index('game', tmp_path, [{'path': 'data.bin'}])
    peer.set_shared_files({'game': ['data.bin']})
    assert not peer.indexes and not peer.roots and not peer.shared_games
