import hashlib

import pytest

from lantool.filesync import client, server
from lantool.filesync.index import CHUNK, PART_SUFFIX
from lantool.trust.signing import generate_keypair


async def test_allocated_corrupt_partial_can_resume_on_nearly_full_disk(tmp_path, monkeypatch):
    private, public = generate_keypair()
    root = tmp_path / 'host'
    (root / 'game').mkdir(parents=True)
    payload = b'a' * CHUNK
    (root / 'game' / 'data.bin').write_bytes(payload)
    dest = tmp_path / 'dest'
    dest.mkdir()
    part = dest / ('data.bin' + PART_SUFFIX)
    part.write_bytes(b'b' * CHUNK)
    monkeypatch.setattr(client.shutil, 'disk_usage', lambda _: type('Usage', (), {'free': 4096})())
    host = server.FileSyncServer(private, root, host='127.0.0.1', port=0)
    await host.start()
    try:
        result = await client.sync_game('127.0.0.1', host.port, public, 'game', dest)
        assert result.ok, result.error
        assert (dest / 'data.bin').read_bytes() == payload
    finally:
        await host.stop()


def test_sparse_partial_counts_only_physical_allocation(tmp_path, monkeypatch):
    part = tmp_path / 'partial'
    part.write_bytes(b'x' * 100)
    actual_stat = type(part).stat
    def sparse_stat(path, **kwargs):
        if path == part:
            return type('Stat', (), {'st_size': CHUNK, 'st_blocks': 1, 'st_mode': 0o100600})()
        return actual_stat(path, **kwargs)
    monkeypatch.setattr(type(part), 'stat', sparse_stat)
    assert client._allocated_partial_bytes(part, CHUNK) == 512


async def test_manual_verify_does_not_cache_tree_changed_after_hashing(tmp_path, monkeypatch):
    private, _ = generate_keypair()
    game = tmp_path / 'game'
    game.mkdir()
    target = game / 'data.bin'
    target.write_bytes(b'old')
    host = server.FileSyncServer(private, tmp_path)
    real_build = server.build_index
    def changing_build(*args, **kwargs):
        result = real_build(*args, **kwargs)
        target.write_bytes(b'new content')
        return result
    monkeypatch.setattr(server, 'build_index', changing_build)
    with pytest.raises(OSError, match='changed while indexing'):
        await host.signed_index('game', verify=True)
    assert 'game' not in host._index_snapshots


def test_signing_stamp_survives_restart_and_clock_rollback(tmp_path, monkeypatch):
    private, _ = generate_keypair()
    cache = tmp_path / 'cache.json'
    monkeypatch.setattr(server.time, 'time', lambda: 2000)
    first = server.FileSyncServer(private, tmp_path, cache_path=cache)
    issued = first._stamp()
    monkeypatch.setattr(server.time, 'time', lambda: 1000)
    restarted = server.FileSyncServer(private, tmp_path, cache_path=cache)
    assert restarted._stamp() > issued
    other, _ = generate_keypair()
    assert server.FileSyncServer(other, tmp_path, cache_path=cache)._stamp_path != first._stamp_path


def test_stamp_is_not_published_when_persistence_fails(tmp_path, monkeypatch):
    private, _ = generate_keypair()
    host = server.FileSyncServer(private, tmp_path, cache_path=tmp_path / 'cache.json')
    def fail(*args):
        raise OSError('locked')
    monkeypatch.setattr(server.os, 'replace', fail)
    with pytest.raises(OSError, match='locked'):
        host._stamp()
    assert host._issued_last == 0


def test_corrupt_signing_counter_fails_closed(tmp_path):
    private, _ = generate_keypair()
    cache = tmp_path / 'cache.json'
    host = server.FileSyncServer(private, tmp_path, cache_path=cache)
    host._stamp_path.write_text('{broken', encoding='utf-8')
    with pytest.raises(OSError, match='signing counter'):
        server.FileSyncServer(private, tmp_path, cache_path=cache)


async def test_missing_peer_piece_is_retried_when_host_stays_unavailable(tmp_path, monkeypatch):
    from lantool.filesync.scheduler import Scheduler
    from lantool.filesync.peer import PeerFileServer
    payload = b'a' * CHUNK
    (tmp_path / 'data.bin').write_bytes(payload)
    entry = {'path': 'data.bin', 'size': len(payload),
             'sha256': hashlib.sha256(payload).hexdigest(),
             'pieces': [hashlib.sha256(payload).hexdigest()]}
    peer = PeerFileServer(tmp_path, host='127.0.0.1', port=0)
    peer.register_index('game', tmp_path, [entry])
    peer.set_shared_files({'game': ['data.bin']})
    real_send = peer._send_verified_piece
    calls = []
    async def missing_once(writer, *args):
        calls.append(True)
        if len(calls) == 1:
            return await peer._reply(writer, 404)
        return await real_send(writer, *args)
    monkeypatch.setattr(peer, '_send_verified_piece', missing_once)
    monkeypatch.setattr(client, 'PEER_LACKS_RETRY_DELAY', .01)
    await peer.start()
    result = client.SyncResult()
    result._scheduler = Scheduler(1)
    result._live_sources = lambda: [('127.0.0.1', peer.port, True)]
    dest = tmp_path / 'dest'
    dest.mkdir()
    try:
        await client._download('127.0.0.1', 1, 'game', entry, dest, .1, lambda _: None, result)
        assert len(calls) == 2
        assert (dest / 'data.bin').read_bytes() == payload
    finally:
        await peer.stop()
