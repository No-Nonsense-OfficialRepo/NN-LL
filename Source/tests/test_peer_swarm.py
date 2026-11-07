import asyncio
import os
from lantool.filesync.server import FileSyncServer
from lantool.filesync.peer import PeerFileServer
from lantool.filesync.client import sync_game, _request
from lantool.filesync.index import CHUNK, PART_SUFFIX, build_index
from lantool.trust.signing import generate_keypair
from lantool.filesync.scheduler import Scheduler


async def test_partial_peer_custom_folder_and_live_sources(tmp_path):
    private, public = generate_keypair()
    root = tmp_path / 'host'
    game = root / 'game'
    game.mkdir(parents=True)
    data = os.urandom(CHUNK * 5 + 9)
    (game / 'archive.bin').write_bytes(data)
    server = FileSyncServer(private, root, host='127.0.0.1', port=0)
    peer = PeerFileServer(tmp_path, host='127.0.0.1', port=0)
    await server.start()
    await peer.start()
    dest = tmp_path / 'Already Named Game'
    dest.mkdir()
    part = dest / ('archive.bin' + PART_SUFFIX)
    part.write_bytes(data[:CHUNK] + bytes(len(data) - CHUNK))
    files = build_index('game', game)['files']
    peer.register_index('game', dest, files)
    peer.set_shared_files({'game': ['archive.bin']})
    calls = []
    def live():
        calls.append(1)
        return [{'host': '127.0.0.1', 'port': peer.port, 'games': ['game']}]
    try:
        status, _, reader, writer = await _request('127.0.0.1', peer.port, '/piece/game/archive.bin', 2, 0, CHUNK-1)
        assert status == 206
        assert await reader.readexactly(CHUNK) == data[:CHUNK]
        writer.close()
        status, _, reader, writer = await _request('127.0.0.1', peer.port, '/piece/game/archive.bin', 2, CHUNK, 2*CHUNK-1)
        assert status == 404  # Unverified preallocated bytes must not be shared.
        writer.close()
        result = await sync_game('127.0.0.1', server.port, public, 'game', tmp_path/'download', peers=live)
        assert result.ok, result.error
        assert (tmp_path/'download'/'archive.bin').read_bytes() == data
        assert len(calls) >= 6
    finally:
        await peer.stop()
        await server.stop()


async def test_scheduler_budget_and_backoff():
    scheduler = Scheduler(12)
    peak = 0
    async def request():
        nonlocal peak
        async with scheduler:
            peak = max(peak, scheduler.active)
            await asyncio.sleep(.01)
    await asyncio.gather(*(request() for _ in range(30)))
    assert peak == 4
    source = ('localhost', 1, True)
    scheduler.failure(source)
    assert scheduler.limit == 3
    assert scheduler.order([source, ('localhost', 2, False)], 0)[-1] == source


async def test_paused_peer_closes_requests_then_resumes_sharing(tmp_path):
    game = tmp_path/'game'
    game.mkdir()
    (game/'file.bin').write_bytes(b'verified file')
    peer = PeerFileServer(tmp_path,host='127.0.0.1',port=0)
    peer.set_shared_files({'game':['file.bin']})
    await peer.start()
    try:
        peer.set_paused(True)
        reader,writer = await asyncio.open_connection('127.0.0.1',peer.port)
        # Paused peers answer 503 (not a silent close) so leechers move on without a failure penalty.
        assert (await asyncio.wait_for(reader.read(),1)).startswith(b'HTTP/1.0 503 ')
        writer.close()
        assert peer.shared_games == {'game'}
        peer.set_paused(False)
        status,_,reader,writer = await _request('127.0.0.1',peer.port,'/piece/game/file.bin',1,0,12)
        assert status == 206
        assert await reader.readexactly(13) == b'verified file'
        writer.close()
    finally:
        await peer.stop()


async def test_paused_peer_answers_503_to_a_client_that_already_sent_its_request(tmp_path):
    game = tmp_path/'game'
    game.mkdir()
    (game/'file.bin').write_bytes(b'verified file')
    peer = PeerFileServer(tmp_path,host='127.0.0.1',port=0)
    peer.set_shared_files({'game':['file.bin']})
    await peer.start()
    try:
        peer.set_paused(True)
        # The request head must be consumed before the 503, or closing with unread bytes can reset the connection.
        status,headers,reader,writer = await _request('127.0.0.1',peer.port,'/piece/game/file.bin',2,0,12)
        assert status == 503
        assert await asyncio.wait_for(reader.read(),2) == b''
        writer.close()
        reader,writer = await asyncio.open_connection('127.0.0.1',peer.port)
        writer.write(b'GET /piece/game/file.bin HTTP/1.0\r\nRange: bytes=0-12\r\n' + b'X-Pad: ' + b'a'*3000 + b'\r\n\r\n')
        await writer.drain()
        assert (await asyncio.wait_for(reader.read(),2)).startswith(b'HTTP/1.0 503 ')
        writer.close()
    finally:
        await peer.stop()


async def test_new_pieces_are_uploadable_before_game_completes(tmp_path):
    private, public = generate_keypair()
    game = tmp_path/'host'/'game'
    game.mkdir(parents=True)
    data = os.urandom(CHUNK * 3 + 5)
    (game/'large.bin').write_bytes(data)
    server = FileSyncServer(private, game.parent, host='127.0.0.1', port=0)
    peer = PeerFileServer(tmp_path, host='127.0.0.1', port=0)
    await server.start()
    await peer.start()
    observed = []
    async def index(gid, dest, files):
        peer.register_index(gid, dest, files)
    async def piece(gid, dest, entry, number):
        peer.set_shared_files({gid: [entry['path']]})
        start = number * CHUNK
        length = min(CHUNK, len(data)-start)
        assert not (dest/'large.bin').exists()
        status, _, reader, writer = await _request('127.0.0.1', peer.port,
            '/piece/game/large.bin', 2, start, start+length-1)
        try:
            assert status == 206
            assert await reader.readexactly(length) == data[start:start+length]
            observed.append(number)
        finally:
            writer.close()
    try:
        result = await sync_game('127.0.0.1', server.port, public, 'game', tmp_path/'client',
                                 on_index=index, on_piece=piece)
        assert result.ok, result.error
        assert sorted(observed) == [0, 1, 2, 3]
    finally:
        await peer.stop()
        await server.stop()
