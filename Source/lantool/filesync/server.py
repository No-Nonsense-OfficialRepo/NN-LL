"""Host side of F8: serves signed per-game indexes and resumable file downloads over asyncio HTTP/1.0."""
from __future__ import annotations
import asyncio, hashlib, json, logging, os, re, sys, threading, time, uuid, weakref
from collections import OrderedDict
from pathlib import Path
from urllib.parse import unquote, parse_qs

from ..trust.signing import sign_obj
from .activity import ActivityTracker
from .index import (CHUNK, GAME_ID_RE, HashCache, SqliteHashCache, PathError, IndexCancelled,
                    build_index, is_internal, safe_join, run_hash_work, finish_disk_work)

SYNC_PORT = 47803
_RANGE_RE = re.compile(r"^bytes=(\d+)-(\d*)$")
HEADER_TIMEOUT = 10.0
SNAPSHOT_LIMIT = 8
SNAPSHOT_BYTES_LIMIT = 64 * 1024 * 1024
SNAPSHOT_MAX_AGE = 24 * 60 * 60


def _object_bytes(value):
    """Estimate retained Python objects, including piece hashes and fingerprints."""
    seen = set()
    def size(item):
        if id(item) in seen:
            return 0
        seen.add(id(item))
        total = sys.getsizeof(item)
        if isinstance(item, dict):
            total += sum(size(k) + size(v) for k, v in item.items())
        elif isinstance(item, (tuple, list)):
            total += sum(size(v) for v in item)
        return total
    return size(value)


def _tree_fingerprint(root, *, cancelled=None):
    """Cheap metadata identity for an index snapshot; content authenticity remains in its hashes."""
    rows = []
    root = Path(root)
    for directory, dirs, names in os.walk(root, followlinks=False):
        if cancelled and cancelled():
            raise IndexCancelled("indexing cancelled")
        dirs.sort()
        for name in sorted(names):
            if is_internal(name):
                continue
            path = Path(directory) / name
            if path.is_symlink():
                continue
            try:
                stat = path.stat()
            except OSError:
                raise
            rows.append((path.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns))
    return tuple(rows)


def _status(code: int) -> bytes:
    text = {200: "OK", 202: "Accepted", 206: "Partial Content", 403: "Forbidden", 404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error",
            416: "Range Not Satisfiable"}[code]
    return f"HTTP/1.0 {code} {text}\r\n".encode()


class FileSyncServer:
    """library_root/<game_id>/... is the served tree. `requests` logs (route, range_start, bytes_sent) for tests/dashboard."""
    def __init__(self, priv_b64: str, library_root, host="0.0.0.0", port=SYNC_PORT, cache_path=None,
                 library_provider=None, *, admission=None):
        self.priv, self.root, self.host, self.port = priv_b64, Path(library_root), host, port
        self._has_library_provider = library_provider is not None
        self.library_provider = library_provider or (lambda: {})
        self.admission = admission
        self.cache = SqliteHashCache(cache_path) if cache_path and str(cache_path).endswith('.sqlite3') else HashCache(cache_path)
        self.requests: list[tuple[str, int, int]] = []
        self.bytes_sent = 0
        self._uploads = asyncio.Semaphore(8)
        self._uploads_by_ip = weakref.WeakValueDictionary()
        self.activity = ActivityTracker()  # bytes sent per (remote ip, game), for the Downloads page
        self._server = None
        # Active callers (including waiters) retain the lock; idle games do not.
        self._index_locks = weakref.WeakValueDictionary()
        self._index_jobs = {}
        self._current_index_jobs = {}
        # Unsigned snapshots are reusable only while the complete path/size/mtime
        # fingerprint still matches. Sign with a fresh stamp for every response.
        self._index_snapshots = OrderedDict()
        self._snapshot_sizes = {}
        self._snapshot_times = {}
        self._stopping = threading.Event()
        self._issued_last = 0
        # The counter belongs to this signing identity, not to any game cache.
        identity = hashlib.sha256(priv_b64.encode('ascii')).hexdigest()[:24]
        self._stamp_path = (Path(cache_path).with_name('host-issued-' + identity + '.json')
                            if cache_path else None)
        if self._stamp_path and self._stamp_path.exists():
            try:
                saved = json.loads(self._stamp_path.read_text(encoding='utf-8'))
                issued = saved['issued']
                if type(issued) is not int or issued < 0:
                    raise ValueError('invalid signing counter')
                self._issued_last = issued
            except (OSError, ValueError, KeyError, TypeError) as exc:
                if isinstance(self.cache, SqliteHashCache):
                    self.cache.close()
                raise OSError('Could not read Host signing counter; restore its backup before reopening the room.') from exc
        self._handlers = set()
        self._writers = set()
        self._credentials = {}
        self._library_lock = asyncio.Lock()
        self._library_cached = None
        self._art_cache = OrderedDict()
        self._connections_by_ip = {}

    async def start(self):
        self._stopping.clear()
        tls = self.admission.listener_options() if self.admission else {}
        self._server = await asyncio.start_server(self._handle, self.host, self.port, **tls)
        self.port = self._server.sockets[0].getsockname()[1]  # supports port=0 in tests

    async def stop(self):
        self._stopping.set()
        jobs = [job['task'] for job in self._index_jobs.values() if not job['task'].done()]
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        server, self._server = self._server, None
        if server:
            server.close()  # stop accepting first
        for writer in tuple(self._writers):
            # abort(), not close(): close() waits for the write buffer to flush, and a stalled client never drains it,
            # so wait_closed() on Python 3.12+ would block until its timeout.
            try:
                writer.transport.abort()
            except Exception:
                writer.close()
        handlers = tuple(task for task in self._handlers if task is not asyncio.current_task())
        for task in handlers:
            task.cancel()
        if handlers:
            await asyncio.gather(*handlers, return_exceptions=True)
        if server:
            try:
                await asyncio.wait_for(server.wait_closed(), 5)
            except asyncio.TimeoutError:
                pass
        if isinstance(self.cache, SqliteHashCache):
            self.cache.close()

    def games(self) -> list[str]:
        if not self._has_library_provider:
            return sorted(p.name for p in self.root.iterdir()
                          if p.is_dir() and GAME_ID_RE.fullmatch(p.name))
        # Only offer games that _game_root() will actually serve, so the list and the server agree.
        return sorted(gid for gid, manifest in self.library_provider().items()
                      if GAME_ID_RE.fullmatch(gid) and manifest.get("enabled", True)
                      and self._game_root(gid) is not None)

    def _game_root(self, game_id: str):
        manifest = self.library_provider().get(game_id)
        if not self._has_library_provider:
            root = (self.root / game_id).resolve()
        else:
            if not manifest or not manifest.get("enabled", True):
                return None
            root = Path(manifest.get("_game_dir", self.root / game_id)).resolve()
        base = self.root.resolve()
        if root.parent != base or not root.is_dir():
            return None
        return root

    def _stamp(self) -> int:
        """Persist before publishing so clock rollback across restarts cannot replay data."""
        issued = max(int(time.time() * 1000), self._issued_last + 1)
        if self._stamp_path:
            self._stamp_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self._stamp_path.with_name(self._stamp_path.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('w', encoding='utf-8') as stream:
                    json.dump({'version': 1, 'issued': issued}, stream)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, self._stamp_path)
            finally:
                temporary.unlink(missing_ok=True)
        self._issued_last = issued
        return issued

    def _drop_snapshot(self, game_id):
        self._index_snapshots.pop(game_id, None)
        self._snapshot_sizes.pop(game_id, None)
        self._snapshot_times.pop(game_id, None)

    def _remember_snapshot(self, game_id, fingerprint, index):
        self._drop_snapshot(game_id)
        snapshot = (fingerprint, index)
        size = _object_bytes(snapshot)
        # A single enormous index remains usable for this response without
        # retaining it for the entire room lifetime.
        if size > SNAPSHOT_BYTES_LIMIT:
            return
        self._index_snapshots[game_id] = snapshot
        self._snapshot_sizes[game_id] = size
        self._snapshot_times[game_id] = time.monotonic()
        while (len(self._index_snapshots) > SNAPSHOT_LIMIT or
               sum(self._snapshot_sizes.values()) > SNAPSHOT_BYTES_LIMIT):
            self._drop_snapshot(next(iter(self._index_snapshots)))

    def _prune_index_state(self):
        active = set(self.games())
        for game_id in tuple(self._index_snapshots):
            if game_id not in active:
                self._drop_snapshot(game_id)
        now = time.monotonic()
        retained_bytes = 0
        finished = sorted((job for job in self._index_jobs.values() if job['finished_at']),
                          key=lambda job: job['finished_at'], reverse=True)
        for position, job in enumerate(finished):
            retained_bytes += job.get('result_bytes', 0)
            if (position >= 16 or now - job['finished_at'] > 60 or job['game'] not in active or
                    retained_bytes > SNAPSHOT_BYTES_LIMIT):
                self._index_jobs.pop(job['id'], None)
                if self._current_index_jobs.get(job['game']) is job:
                    self._current_index_jobs.pop(job['game'], None)

    async def signed_index(self, game_id: str, *, progress=None, verify=False) -> dict:
        """Build (hash-cached) and sign the index for one game. Hashing runs in a worker thread."""
        game_dir = self._game_root(game_id)
        if game_dir is None:
            raise PathError("game is not in the active playlist")
        lock = self._index_locks.setdefault(game_id, asyncio.Lock())
        async with lock:
            self._prune_index_state()
            fingerprint = None
            if not verify:
                fingerprint = await run_hash_work(_tree_fingerprint, game_dir, stop=self._stopping)
                cached = self._index_snapshots.get(game_id)
                if (cached and cached[0] == fingerprint and
                        time.monotonic() - self._snapshot_times[game_id] < SNAPSHOT_MAX_AGE):
                    idx = cached[1]
                    self._index_snapshots.move_to_end(game_id)
                else:
                    expired = bool(cached and time.monotonic() - self._snapshot_times[game_id] >= SNAPSHOT_MAX_AGE)
                    idx = await run_hash_work(build_index, game_id, game_dir, self.cache,
                                              stop=self._stopping, progress=progress, verify=expired)
                    # build_index verifies a stable before/after tree snapshot. Re-fingerprint
                    # after it completes so a concurrent change cannot label an old index current.
                    after = await run_hash_work(_tree_fingerprint, game_dir, stop=self._stopping)
                    if after != fingerprint:
                        raise OSError(f"Game files changed while indexing: {game_id}. Retry the download.")
                    self._remember_snapshot(game_id, fingerprint, idx)
            else:
                before = await run_hash_work(_tree_fingerprint, game_dir, stop=self._stopping)
                idx = await run_hash_work(build_index, game_id, game_dir, self.cache,
                                          stop=self._stopping, progress=progress, verify=True)
                fingerprint = await run_hash_work(_tree_fingerprint, game_dir, stop=self._stopping)
                if fingerprint != before:
                    self._drop_snapshot(game_id)
                    raise OSError(f"Game files changed while indexing: {game_id}. Retry the download.")
                self._remember_snapshot(game_id, fingerprint, idx)
            try:
                await finish_disk_work(self.cache.save)
            except OSError:
                pass  # the hash cache is an optimisation; the signed index is still correct
        return sign_obj(self.priv, {**idx, "issued": self._stamp()})

    def _start_index_job(self, game_id, *, verify=False):
        if not verify:
            current = self._current_index_jobs.get(game_id)
            if current and not current['task'].done():
                return current
        job = {'id': uuid.uuid4().hex, 'game': game_id, 'state': 'running',
               'done': 0, 'total': 0, 'files_done': 0, 'files_total': 0,
               'file': '', 'error': '', 'result': None, 'finished_at': 0}
        self._index_jobs[job['id']] = job
        self._current_index_jobs[game_id] = job
        job['task'] = asyncio.create_task(self._run_index_job(job, verify))
        # Keep completed results long enough for clients already polling them.
        self._prune_index_state()
        return job

    async def _run_index_job(self, job, verify):
        def progress(done, total, files_done, files_total, filename):
            job.update(done=done, total=total, files_done=files_done,
                       files_total=files_total, file=filename)
        try:
            if getattr(self.signed_index, '__func__', None) is FileSyncServer.signed_index:
                job['result'] = await self.signed_index(job['game'], progress=progress, verify=verify)
            else:
                job['result'] = await self.signed_index(job['game'])
            job['state'] = 'ready'
        except asyncio.CancelledError:
            job['state'], job['error'] = 'error', 'Host stopped indexing.'
            raise
        except Exception as exc:
            job['state'], job['error'] = 'error', str(exc) or type(exc).__name__
            logging.getLogger(__name__).exception('Could not index game %s', job['game'])
        finally:
            job['result_bytes'] = _object_bytes(job['result']) if job['result'] else 0
            job['finished_at'] = time.monotonic()

    async def recheck_index(self, game_id):
        if self._game_root(game_id) is None:
            raise PathError('game is not in the active playlist')
        job = self._start_index_job(game_id, verify=True)
        await job['task']
        if job['state'] != 'ready':
            raise OSError(job['error'])
        return job['result']

    async def index_status(self):
        """Snapshot per-game progress on the file server's event loop for the Host UI."""
        self._prune_index_state()
        result = {game_id: {'state': 'ready', 'done': 1, 'total': 1}
                  for game_id in self._index_snapshots}
        for game_id, job in self._current_index_jobs.items():
            result[game_id] = {key: job[key] for key in ('state', 'done', 'total', 'files_done', 'files_total', 'error')}
            result[game_id]['job_id'] = job['id']
        return result

    async def prewarm(self):
        """Hash every game once at host start so the first client does not wait on a 20 GB hash."""
        for g in self.games():
            try:
                await self.signed_index(g)
            except (PathError, OSError, ValueError) as exc:
                # One unreadable game must not stop the others from being hashed. IndexCancelled still propagates.
                logging.getLogger(__name__).warning("Could not pre-hash game %s: %s", g, exc)

    # -- HTTP ---------------------------------------------------------------------------------------------------
    async def _handle(self, reader, writer):
        # Bound sockets waiting for an upload slot. Each request otherwise gets
        # its own asyncio task and a slow client can accumulate them indefinitely.
        if len(self._writers) >= 64:
            writer.close()
            return
        peer = writer.get_extra_info('peername')
        address = peer[0] if peer else ''
        if self._connections_by_ip.get(address, 0) >= 16:
            writer.close()
            return
        self._connections_by_ip[address] = self._connections_by_ip.get(address, 0) + 1
        task = asyncio.current_task()
        self._handlers.add(task)
        self._writers.add(writer)
        try:
            for _ in range(64):
                deadline = asyncio.get_running_loop().time() + HEADER_TIMEOUT
                async def read_header():
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        raise asyncio.TimeoutError()
                    return await asyncio.wait_for(reader.readline(), remaining)
                raw_line = await read_header()
                header_bytes = len(raw_line)
                line = raw_line.decode('latin-1')
                if not line:
                    break
                headers: dict[str, str] = {}
                for _header in range(100):
                    raw_header = await read_header()
                    header_bytes += len(raw_header)
                    if header_bytes > 32768:
                        raise ValueError('Request headers too large')
                    h = raw_header.decode('latin-1')
                    if h in ("\r\n", "\n", ""):
                        break
                    k, _, v = h.partition(":")
                    headers[k.strip().lower()] = v.strip()
                else:
                    raise ValueError('Too many request headers')
                if self.admission:
                    scheme, _, token = headers.get("authorization", "").partition(" ")
                    peer = writer.get_extra_info("peername")
                    ip = peer[0] if peer else ""
                    if scheme != "Bearer" or not self.admission.permits(token, ip=ip):
                        await self._reply(writer, 403)
                        break
                    self._credentials[writer] = token, ip
                parts = line.split()
                if len(parts) < 2 or parts[0] != "GET":
                    await self._reply(writer, 405)
                    break
                route, _, query = parts[1].partition('?')
                path = unquote(route)
                if path.startswith('/index-job/'):
                    await self._index_job(writer, path[len('/index-job/'):], query)
                elif path.startswith("/index/"):
                    await self._index(writer, path[len("/index/"):])
                elif path == "/library":
                    await self._library(writer)
                elif path.startswith("/art/"):
                    await self._art(writer, path[len("/art/"):])
                elif path.startswith("/file/"):
                    peer = writer.get_extra_info("peername")
                    peer_ip = peer[0] if peer else ""
                    per_ip = self._uploads_by_ip.get(peer_ip)
                    if per_ip is None:
                        per_ip = self._uploads_by_ip[peer_ip] = asyncio.Semaphore(6)
                    keep_alive = (headers.get("connection", "").lower() == "keep-alive"
                                  and bool(headers.get("range")))
                    async with per_ip:
                        async with self._uploads:
                            complete = await asyncio.wait_for(self._file(
                                writer, path[len("/file/"):], headers.get("range"), keep_alive=keep_alive), 120)
                    if keep_alive and complete and not writer.is_closing():
                        continue
                else:
                    await self._reply(writer, 404)
                break
        except (OSError, asyncio.TimeoutError, ConnectionError, ValueError, IndexCancelled):  # ValueError: over-long request line
            pass
        finally:
            writer.close()
            self._credentials.pop(writer, None)
            self._writers.discard(writer)
            self._handlers.discard(task)
            count = self._connections_by_ip[address] - 1
            if count:
                self._connections_by_ip[address] = count
            else:
                self._connections_by_ip.pop(address, None)

    async def _reply(self, writer, code: int, body: bytes = b"", extra: str = ""):
        if code != 403 and not self._permitted(writer):
            return
        writer.write(_status(code) + f"Content-Length: {len(body)}\r\n{extra}\r\n".encode() + body)
        await writer.drain()

    def _permitted(self, writer):
        if self.admission:
            token, ip = self._credentials.get(writer, ("", ""))
            return self.admission.permits(token, ip=ip)
        return True

    async def _index(self, writer, game_id: str):
        if not GAME_ID_RE.fullmatch(game_id) or self._game_root(game_id) is None:
            return await self._reply(writer, 404)
        body = json.dumps(await self.signed_index(game_id)).encode()
        self.requests.append((f"index/{game_id}", 0, len(body)))
        if len(self.requests) > 1000:
            del self.requests[:-500]  # keep the log bounded
        await self._reply(writer, 200, body, "Content-Type: application/json\r\n")

    async def _index_job(self, writer, game_id, query):
        if not GAME_ID_RE.fullmatch(game_id) or self._game_root(game_id) is None:
            return await self._reply(writer, 404)
        token = parse_qs(query).get('job', [''])[0]
        job = self._index_jobs.get(token) if token else self._start_index_job(game_id)
        if not job or job['game'] != game_id:
            return await self._reply(writer, 404)
        if job['state'] == 'ready':
            body = json.dumps(job['result']).encode()
            return await self._reply(writer, 200, body, 'Content-Type: application/json\r\n')
        status = 500 if job['state'] == 'error' else 202
        public = {k: job[k] for k in ('id', 'state', 'done', 'total', 'files_done',
                                      'files_total', 'file', 'error')}
        await self._reply(writer, status, json.dumps(public).encode(),
                          'Content-Type: application/json\r\n')

    async def _library(self, writer):
        async with self._library_lock:
            manifests = list(self.library_provider().values())
            def fingerprint():
                records = []
                for manifest in manifests:
                    try:
                        root = Path(manifest.get('_game_dir', self.root)).resolve()
                        exe = safe_join(root, manifest.get('exe', ''))
                        stat = exe.stat()
                        stamp = (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
                    except (OSError, ValueError, TypeError):
                        stamp = None
                    records.append((repr(manifest), stamp))
                return tuple(records)
            key = await finish_disk_work(fingerprint)
            cached = self._library_cached
            if cached and cached[0] == key and time.monotonic() - cached[1] < 2:
                body = json.dumps(sign_obj(self.priv, {'type': 'library', 'issued': self._stamp(), 'games': cached[2]})).encode()
                await self._reply(writer, 200, body, 'Content-Type: application/json\r\n')
            else:
                await self._build_library(writer, manifests, key)

    async def _build_library(self, writer, manifests, key):
        games = []
        for manifest in manifests:
            public_manifest = {k: v for k, v in manifest.items()
                               if k not in ("_dir", "_game_dir", "_art_path", "_icon_path", "install_dir", "enabled")}
            # The client uses this signed size with the Host-selected relative
            # exe path for a fast installed-game check. No game-wide hash scan
            # is needed just to decide whether to launch.
            game_dir = Path(manifest.get("_game_dir", self.root)).resolve()
            exe_rel = manifest.get("exe")
            if isinstance(exe_rel, str):
                try:
                    exe_path = (game_dir / exe_rel).resolve()
                    if game_dir in exe_path.parents and exe_path.suffix.casefold() == ".exe" \
                            and exe_path.is_file():
                        public_manifest["exe_size"] = exe_path.stat().st_size
                        from ..install_manifest import executable_record
                        record = await run_hash_work(executable_record, game_dir, exe_rel, stop=self._stopping)
                        public_manifest["exe_sha256"] = record["sha256"]
                except (OSError, ValueError):
                    pass
            games.append(public_manifest)
        self._library_cached = (key, time.monotonic(), games)
        body = json.dumps(sign_obj(self.priv, {"type": "library", "issued": self._stamp(), "games": games})).encode()
        await self._reply(writer, 200, body, "Content-Type: application/json\r\n")

    async def _art(self, writer, rest: str):
        # /art/<gid>           legacy route: the image that hashes to icon_sha256
        #                      (exe icon when the Host has one, else the cover)
        # /art/<gid>/portrait  the 600x900 cover, verified against art_sha256
        game_id, _, kind = rest.partition("/")
        if not GAME_ID_RE.fullmatch(game_id) or kind not in ("", "portrait"):
            return await self._reply(writer, 404)
        manifest = self.library_provider().get(game_id)
        if not manifest or not manifest.get("enabled", True):
            return await self._reply(writer, 404)
        if kind == "portrait":
            path_key, hash_key = "_art_path", "art_sha256"
        else:
            path_key, hash_key = ("_icon_path", "icon_sha256") if manifest.get("_icon_path") \
                else ("_art_path", "icon_sha256")
        if not manifest.get(path_key):
            return await self._reply(writer, 404)
        try:
            path = Path(manifest[path_key])
            stat = await finish_disk_work(path.stat)
            if stat.st_size > 12 * 1024 * 1024:
                return await self._reply(writer, 404)
            cache_key = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns, manifest.get(hash_key))
            data = self._art_cache.get(cache_key)
            if data is None:
                def read_art():
                    with path.open('rb') as stream:
                        return stream.read(12 * 1024 * 1024 + 1)
                data = await finish_disk_work(read_art)
            else:
                self._art_cache.move_to_end(cache_key)
        except OSError:
            return await self._reply(writer, 404)
        if len(data) > 12 * 1024 * 1024 or not manifest.get(hash_key) or \
                hashlib.sha256(data).hexdigest() != manifest[hash_key]:
            return await self._reply(writer, 404)
        self._art_cache[cache_key] = data
        self._art_cache.move_to_end(cache_key)
        while len(self._art_cache) > 8 or sum(map(len, self._art_cache.values())) > 24 * 1024 * 1024:
            self._art_cache.popitem(last=False)
        await self._reply(writer, 200, data, "Content-Type: image/png\r\n")

    async def _file(self, writer, rest: str, range_header: str | None, *, keep_alive=False):
        game_id, _, rel = rest.partition("/")
        try:
            if not GAME_ID_RE.fullmatch(game_id):
                raise PathError("bad game id")
            game_root = self._game_root(game_id)
            if game_root is None:
                raise PathError("game not in active playlist")
            full = safe_join(game_root, rel)
            if is_internal(full.name) or full.is_symlink() or not full.is_file():
                raise PathError("not servable")
        except (PathError, OSError):
            return await self._reply(writer, 404)
        size = full.stat().st_size
        start, end, code = 0, size - 1, 200
        if range_header:
            m = _RANGE_RE.match(range_header)
            if not m:
                return await self._reply(writer, 416, extra=f"Content-Range: bytes */{size}\r\n")
            start = int(m.group(1))
            end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
            if start >= size or start > end:
                return await self._reply(writer, 416, extra=f"Content-Range: bytes */{size}\r\n")
            code = 206
        length = end - start + 1
        extra = f"Content-Type: application/octet-stream\r\nContent-Length: {length}\r\n"
        if code == 206:
            extra += f"Content-Range: bytes {start}-{end}/{size}\r\n"
        if keep_alive and code == 206:
            extra += "Connection: keep-alive\r\n"
        writer.write(_status(code) + extra.encode() + b"\r\n")
        sent = 0
        peer = writer.get_extra_info("peername")
        peer_ip = peer[0] if peer else ""
        with open(full, "rb") as f:
            f.seek(start)
            while sent < length:
                block = await finish_disk_work(f.read, min(CHUNK, length - sent))
                if not block or not self._permitted(writer):
                    break  # file shrank after we promised a length; client's hash check catches it
                writer.write(block)
                await writer.drain()
                sent += len(block)
                self.activity.record(peer_ip, game_id, len(block))
                self.bytes_sent += len(block)
        self.requests.append((f"file/{game_id}/{rel}", start, sent))
        if len(self.requests) > 1000:
            del self.requests[:-500]  # keep the log bounded
        return sent == length
