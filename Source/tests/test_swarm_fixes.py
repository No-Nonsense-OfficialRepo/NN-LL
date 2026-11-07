"""Regression tests for the swarm audit fixes: peer 404 carries no penalty, cache-save and rename
failures don't fail a sync, and stopping a server with a stuck client returns promptly."""
import asyncio
import os

from lantool.filesync.server import FileSyncServer
from lantool.filesync.peer import PeerFileServer
from lantool.filesync.client import sync_game
from lantool.filesync.index import CHUNK, HashCache, replace_file
from lantool.trust.signing import generate_keypair


async def test_peer_that_lacks_a_piece_is_not_penalised(tmp_path):
    private, public = generate_keypair()
    game = tmp_path / 'host' / 'game'
    game.mkdir(parents=True)
    data = os.urandom(CHUNK * 3 + 5)
    (game / 'big.bin').write_bytes(data)
    server = FileSyncServer(private, game.parent, host='127.0.0.1', port=0)
    peer = PeerFileServer(tmp_path, host='127.0.0.1', port=0)  # shares nothing, so every request is a 404
    await server.start()
    await peer.start()
    try:
        peers = lambda: [{'host': '127.0.0.1', 'port': peer.port, 'games': ['game']}]
        result = await sync_game('127.0.0.1', server.port, public, 'game', tmp_path / 'dl', peers=peers)
        assert result.ok, result.error
        assert (tmp_path / 'dl' / 'big.bin').read_bytes() == data
        peer_key = ('127.0.0.1', peer.port, True)
        failures = result._scheduler.sources.get(peer_key, (0, 0, 0))[1]
        assert failures == 0  # "I don't have that piece yet" is not a fault
    finally:
        await peer.stop()
        await server.stop()


async def test_failed_hash_cache_save_does_not_fail_the_sync(tmp_path, monkeypatch):
    private, public = generate_keypair()
    game = tmp_path / 'host' / 'game'
    game.mkdir(parents=True)
    data = os.urandom(CHUNK + 7)
    (game / 'a.bin').write_bytes(data)
    server = FileSyncServer(private, game.parent, host='127.0.0.1', port=0)
    await server.start()

    def broken_save(self):
        raise OSError('disk busy')
    monkeypatch.setattr(HashCache, 'save', broken_save)
    try:
        result = await sync_game('127.0.0.1', server.port, public, 'game', tmp_path / 'dl')
        assert result.ok, result.error
        assert (tmp_path / 'dl' / 'a.bin').read_bytes() == data
    finally:
        await server.stop()


def test_replace_file_rides_out_a_brief_sharing_lock(tmp_path, monkeypatch):
    src = tmp_path / 'a.part'
    dst = tmp_path / 'a.bin'
    src.write_bytes(b'x')
    real_replace = os.replace
    calls = []

    def flaky(a, b):
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError('locked by another process')
        return real_replace(a, b)
    monkeypatch.setattr(os, 'replace', flaky)
    replace_file(src, dst)
    assert dst.read_bytes() == b'x'
    assert len(calls) == 3


async def test_stop_returns_while_clients_are_stuck_mid_transfer(tmp_path):
    private, _ = generate_keypair()
    game = tmp_path / 'host' / 'game'
    game.mkdir(parents=True)
    (game / 'big.bin').write_bytes(os.urandom(CHUNK * 16))
    server = FileSyncServer(private, game.parent, host='127.0.0.1', port=0)
    peer = PeerFileServer(tmp_path / 'host', host='127.0.0.1', port=0)
    await server.start()
    await peer.start()
    peer.set_shared_files({'game': ['big.bin']})
    r1, w1 = await asyncio.open_connection('127.0.0.1', server.port)
    r2, w2 = await asyncio.open_connection('127.0.0.1', peer.port)
    try:
        w1.write(b'GET /file/game/big.bin HTTP/1.0\r\n\r\n')
        w2.write(b'GET /piece/game/big.bin HTTP/1.0\r\nRange: bytes=0-1048575\r\n\r\n')
        await w1.drain()
        await w2.drain()
        await asyncio.sleep(0.3)  # both responses are now waiting on a client that never reads
        await asyncio.wait_for(server.stop(), 5)
        await asyncio.wait_for(peer.stop(), 5)
    finally:
        w1.close()
        w2.close()


async def test_prewarm_skips_a_bad_game_and_keeps_going(tmp_path, monkeypatch):
    import lantool.filesync.server as srv
    private, _ = generate_keypair()
    root = tmp_path / 'lib'
    good = root / 'good'
    good.mkdir(parents=True)
    (good / 'a.bin').write_bytes(b'abc')
    bad = root / 'bad'
    bad.mkdir()
    stray = tmp_path / 'elsewhere' / 'stray'
    stray.mkdir(parents=True)
    library = {
        'bad': {'enabled': True, '_game_dir': str(bad)},
        'stray': {'enabled': True, '_game_dir': str(stray)},
        'good': {'enabled': True, '_game_dir': str(good)},
    }
    server = FileSyncServer(private, root, host='127.0.0.1', port=0, library_provider=lambda: library)
    assert server.games() == ['bad', 'good']  # 'stray' is outside the library root, so it is not offered
    real_build = srv.build_index
    hashed = []

    def flaky(gid, folder, *args, **kwargs):
        if gid == 'bad':
            raise OSError('unreadable')
        hashed.append(gid)
        return real_build(gid, folder, *args, **kwargs)
    monkeypatch.setattr(srv, 'build_index', flaky)
    await server.prewarm()  # must not raise
    assert hashed == ['good']
