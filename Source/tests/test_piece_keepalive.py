"""Opt-in piece connections can serve several verified ranges without reopening TCP."""
import asyncio
import os

from lantool.filesync.index import CHUNK, build_index
from lantool.filesync import client as file_client
from lantool.filesync.peer import PeerFileServer
from lantool.filesync.server import FileSyncServer
from lantool.trust.signing import generate_keypair


async def test_sync_reuses_host_piece_socket(tmp_path, monkeypatch):
    private, public = generate_keypair()
    game = tmp_path / "game"
    game.mkdir()
    content = os.urandom(CHUNK * 3)
    (game / "archive.bin").write_bytes(content)
    server = FileSyncServer(private, tmp_path, host="127.0.0.1", port=0)
    await server.start()
    original = file_client._request
    reused = []

    async def tracked(*args, **kwargs):
        if args[2].startswith("/file/"):
            reused.append(kwargs.get("existing") is not None)
        return await original(*args, **kwargs)

    monkeypatch.setattr(file_client, "_request", tracked)
    try:
        result = await file_client.sync_game("127.0.0.1", server.port, public, "game",
                                             tmp_path / "download", concurrency=1)
        assert result.ok, result.error
        assert (tmp_path / "download" / "archive.bin").read_bytes() == content
        assert reused == [False, True, True]
    finally:
        await server.stop()


async def _piece(reader, writer, route, index, keep_alive):
    start = index * CHUNK
    extra = b"Connection: keep-alive\r\n" if keep_alive else b""
    writer.write(f"GET /{route}/game/archive.bin HTTP/1.0\r\n"
                 f"Range: bytes={start}-{start + CHUNK - 1}\r\n".encode() + extra + b"\r\n")
    await writer.drain()
    status = await asyncio.wait_for(reader.readline(), 3)
    headers = {}
    while (line := await asyncio.wait_for(reader.readline(), 3)) not in (b"\r\n", b"\n", b""):
        key, value = line.decode().split(":", 1)
        headers[key.lower()] = value.strip().lower()
    body = await asyncio.wait_for(reader.readexactly(int(headers["content-length"])), 3)
    return status, headers, body


async def test_host_reuses_only_requested_piece_connection(tmp_path):
    private, _ = generate_keypair()
    game = tmp_path / "game"
    game.mkdir()
    content = os.urandom(CHUNK * 2)
    (game / "archive.bin").write_bytes(content)
    server = FileSyncServer(private, tmp_path, host="127.0.0.1", port=0)
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        for index, keep in ((0, True), (1, False)):
            status, headers, body = await _piece(reader, writer, "file", index, keep)
            assert status.startswith(b"HTTP/1.0 206")
            assert body == content[index * CHUNK:(index + 1) * CHUNK]
            assert (headers.get("connection") == "keep-alive") == keep
        assert await asyncio.wait_for(reader.read(), 3) == b""
        writer.close()
    finally:
        await server.stop()


async def test_peer_reuses_only_requested_verified_piece_connection(tmp_path):
    game = tmp_path / "game"
    game.mkdir()
    content = os.urandom(CHUNK * 2)
    (game / "archive.bin").write_bytes(content)
    peer = PeerFileServer(tmp_path, host="127.0.0.1", port=0)
    peer.register_index("game", game, build_index("game", game)["files"])
    peer.set_shared_files({"game": ["archive.bin"]})
    await peer.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", peer.port)
        for index, keep in ((0, True), (1, False)):
            status, headers, body = await _piece(reader, writer, "piece", index, keep)
            assert status.startswith(b"HTTP/1.0 206")
            assert body == content[index * CHUNK:(index + 1) * CHUNK]
            assert (headers.get("connection") == "keep-alive") == keep
        assert await asyncio.wait_for(reader.read(), 3) == b""
        writer.close()
    finally:
        await peer.stop()
