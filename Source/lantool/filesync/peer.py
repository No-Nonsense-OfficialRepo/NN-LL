"""Serve verified, Host-approved game files to other Clients in the room."""
from __future__ import annotations

import asyncio, hashlib, logging, weakref
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote

from .activity import ActivityTracker
from .index import CHUNK, PART_SUFFIX, GAME_ID_RE, PathError, is_internal, safe_join, finish_disk_work
from .server import _RANGE_RE, _status, _object_bytes

PEER_SYNC_PORT = 47805
PEER_INDEX_LIMIT = 8
PEER_INDEX_BYTES = 64 * 1024 * 1024
log = logging.getLogger(__name__)


class PeerFileServer:
    def __init__(self, game_root, host="0.0.0.0", port=PEER_SYNC_PORT):
        self.root = Path(game_root)
        self.host, self.port = host, port
        self.shared_games: set[str] = set()
        self.shared_files: dict[str, set[str]] = {}
        self.roots = {}
        self.indexes = OrderedDict()
        self._index_sizes = {}
        self._has_registered_indexes = False
        self._uploads = asyncio.Semaphore(8)
        self._uploads_by_ip = weakref.WeakValueDictionary()
        self._server = None
        self.paused = False
        self._writers = set()
        self._handlers = set()
        self.activity = ActivityTracker()  # bytes sent per (remote ip, game), for the Downloads page

    def set_paused(self, paused):
        self.paused = paused
        if paused:
            for writer in tuple(self._writers):
                writer.transport.abort()
            for task in tuple(self._handlers):
                if task is not asyncio.current_task():
                    task.cancel()

    async def wait_idle(self):
        """Wait for uploads and their shielded disk reads to release handles."""
        tasks = tuple(task for task in self._handlers if task is not asyncio.current_task())
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def pause_and_drain(self):
        self.set_paused(True)
        await self.wait_idle()

    async def start(self):
        self.paused = False
        self._server = await asyncio.start_server(self._handle, self.host, self.port)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        self.set_paused(True)
        self.shared_games.clear()
        self.shared_files.clear()
        server, self._server = self._server, None
        if server:
            server.close()
        await self.wait_idle()
        self.roots.clear()
        self.indexes.clear()
        self._index_sizes.clear()
        if server:
            try:
                await asyncio.wait_for(server.wait_closed(), 5)
            except asyncio.TimeoutError:
                pass

    def set_shared_games(self, games):
        previous = self.shared_games
        self.shared_games = {game for game in games if GAME_ID_RE.fullmatch(str(game)) and
                             (not self._has_registered_indexes or game in self.indexes)}
        self.shared_files = {gid: paths for gid, paths in self.shared_files.items()
                             if gid in self.shared_games}
        self._remove_indexes(previous - self.shared_games)

    def set_shared_files(self, files_by_game):
        previous = self.shared_games
        self.shared_files = {str(gid): set(paths) for gid, paths in files_by_game.items()
                             if GAME_ID_RE.fullmatch(str(gid)) and
                             (not self._has_registered_indexes or str(gid) in self.indexes)}
        self.shared_games = set(self.shared_files)
        self._remove_indexes(previous - self.shared_games)

    def _remove_indexes(self, games):
        # Active requests retain their own entry/root references until done.
        for game in games:
            self.roots.pop(game, None)
            self.indexes.pop(game, None)
            self._index_sizes.pop(game, None)

    def register_index(self, game_id, root, files):
        self._has_registered_indexes = True
        self._remove_indexes((game_id,))
        index = {f['path']: f for f in files}
        size = _object_bytes(index)
        if size > PEER_INDEX_BYTES:
            self.shared_games.discard(game_id)
            self.shared_files.pop(game_id, None)
            return
        self.roots[game_id] = Path(root).resolve()
        self.indexes[game_id] = index
        self._index_sizes[game_id] = size
        while len(self.indexes) > PEER_INDEX_LIMIT or sum(self._index_sizes.values()) > PEER_INDEX_BYTES:
            evicted = next(iter(self.indexes))
            self._remove_indexes((evicted,))
            self.shared_games.discard(evicted)
            self.shared_files.pop(evicted, None)

    @staticmethod
    async def _discard_request(reader):
        """Read the request head before answering 503. Closing a socket that still holds unread request bytes
        can reset the connection on Windows, and the leecher would then see an error instead of the 503."""
        async def head():
            for _ in range(100):
                if await reader.readline() in (b"\r\n", b"\n", b""):
                    return
        try:
            await asyncio.wait_for(head(), 0.3)  # a silent client still gets its 503, just slightly later
        except (asyncio.TimeoutError, ValueError):
            pass

    async def _handle(self, reader, writer):
        if len(self._writers) >= 64:
            writer.close()
            return
        if self.paused:
            log.info("refused request from %s: seeder is paused", writer.get_extra_info("peername"))
            try:
                # 503 tells the leecher to try another source later; a silent close looks like a failure to it.
                await self._discard_request(reader)
                writer.write(b"HTTP/1.0 503 Service Unavailable\r\nRetry-After: 2\r\nContent-Length: 0\r\n\r\n")
                await asyncio.wait_for(writer.drain(), 2)
            except (OSError, asyncio.TimeoutError):
                pass
            finally:
                writer.close()
            return
        self._writers.add(writer)
        task = asyncio.current_task()
        self._handlers.add(task)
        try:
            address = writer.get_extra_info("peername")
            peer_ip = address[0] if address else ""
            per_ip = self._uploads_by_ip.get(peer_ip)
            if per_ip is None:
                per_ip = self._uploads_by_ip[peer_ip] = asyncio.Semaphore(6)
            for _ in range(64):
                keep_alive = await asyncio.wait_for(self._serve(reader, writer, per_ip), 30)
                if not keep_alive or writer.is_closing():
                    break
        except (OSError, asyncio.TimeoutError, ValueError):  # ValueError: over-long request line
            writer.close()
        finally:
            self._writers.discard(writer)
            self._handlers.discard(task)
            writer.close()

    async def _serve(self, reader, writer, per_ip):
        try:
            line = (await asyncio.wait_for(reader.readline(), 5)).decode("latin-1")
            if not line:
                return False
            headers = {}
            for _ in range(100):
                item = (await asyncio.wait_for(reader.readline(), 5)).decode("latin-1")
                if item in ("\r\n", "\n", ""):
                    break
                key, _, value = item.partition(":")
                headers[key.strip().lower()] = value.strip()
            parts = line.split()
            if len(parts) < 2 or parts[0] != "GET":
                return await self._reply(writer, 405)
            path = unquote(parts[1].split("?", 1)[0])
            if not path.startswith("/piece/"):
                return await self._reply(writer, 404)
            game_id, _, rel = path[len("/piece/"):].partition("/")
            if game_id not in self.shared_games or not GAME_ID_RE.fullmatch(game_id):
                return await self._reply(writer, 404)
            if rel not in self.shared_files.get(game_id, set()):
                log.info("404 for %s/%s: file not announced as shared yet", game_id, rel)
                return await self._reply(writer, 404)
            try:
                full = safe_join(self.roots.get(game_id, self.root / game_id), rel)
                entry = self.indexes.get(game_id, {}).get(rel)
                partial = full.with_name(full.name + PART_SUFFIX)
                if entry and partial.is_file():
                    full = partial
                if (is_internal(full.name) and not (entry and full.name.endswith(PART_SUFFIX))) or full.is_symlink() or not full.is_file():
                    raise PathError("file not shareable")
            except (PathError, OSError):
                return await self._reply(writer, 404)
            size = full.stat().st_size
            match = _RANGE_RE.match(headers.get("range", ""))
            if not match:
                return await self._reply(writer, 416)
            start = int(match.group(1))
            end = min(int(match.group(2)), size - 1) if match.group(2) else size - 1
            if start >= size or start > end or end - start + 1 > CHUNK:
                return await self._reply(writer, 416)
            length = end - start + 1
            async with per_ip:
                async with self._uploads:
                    return await self._send_verified_piece(
                        writer, full, entry, game_id, start, end, size, length,
                        headers.get("connection", "").lower() == "keep-alive")
        except (OSError, asyncio.TimeoutError, ConnectionError, ValueError):
            return False

    async def _send_verified_piece(self, writer, full, entry, game_id, start, end, size, length, keep_alive):
        def read_piece():
            with full.open('rb') as stream:
                stream.seek(start)
                return stream.read(length)
        block = await finish_disk_work(read_piece)
        if entry:
            pieces = entry.get('pieces') or []
            if (start % CHUNK or start // CHUNK >= len(pieces) or
                    length != min(CHUNK, entry['size'] - start) or
                    hashlib.sha256(block).hexdigest() != pieces[start // CHUNK]):
                return await self._reply(writer, 404)
        if self.paused:
            return await self._reply(writer, 503)
        extra = "Connection: keep-alive\r\n" if keep_alive else ""
        writer.write(_status(206) +
            f"Content-Type: application/octet-stream\r\nContent-Length: {length}\r\n"
            f"Content-Range: bytes {start}-{end}/{size}\r\n{extra}\r\n".encode())
        await writer.drain()
        writer.write(block)
        await writer.drain()
        peer = writer.get_extra_info("peername")
        self.activity.record(peer[0] if peer else "", game_id, len(block))
        return keep_alive

    async def _reply(self, writer, code):
        text = {404: "Not Found", 405: "Method Not Allowed", 416: "Range Not Satisfiable", 503: "Service Unavailable"}[code]
        writer.write(f"HTTP/1.0 {code} {text}\r\nContent-Length: 0\r\n\r\n".encode())
        await writer.drain()
