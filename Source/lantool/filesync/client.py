"""Client side of F8: verify the signed index, diff by hash, download changed files (resumable), verify each."""
from __future__ import annotations
import asyncio, hashlib, json, logging, os, shutil, time
from .scheduler import Scheduler
from .activity import ActivityTracker
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote

from ..trust.signing import verify_obj
from ..trust.freshness import SESSION as FRESHNESS, StaleError
from .index import (CACHE_NAME, CHUNK, PART_SUFFIX, HashCache, diff_index, hash_file,
                    is_internal, replace_file, safe_join, validate_index, run_hash_work, finish_disk_work, check_cancelled)

log = logging.getLogger(__name__)
MAX_INDEX_BYTES = 32 * 1024 * 1024
INDEX_BUILD_TIMEOUT = 300.0
PEER_LACKS_RETRY_DELAY = 2.0


@dataclass
class SyncResult:
    ok: bool = False
    error: str = ""
    downloaded: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)
    bytes_downloaded: int = 0
    resumed: list[str] = field(default_factory=list)
    verified_files: dict[str, list[str]] = field(default_factory=dict)
    _scheduler: Scheduler = field(default_factory=Scheduler, repr=False)
    _live_sources: object = field(default=lambda: [], repr=False)
    _on_piece: object = field(default=None, repr=False)
    _received: ActivityTracker = field(default_factory=ActivityTracker, repr=False)


class _HttpError(Exception):
    pass


class _PeerPaused(Exception):
    """A peer answered 503: it is paused for now. Try another source; no penalty."""
    pass


class _PeerLacksPiece(Exception):
    """A peer answered 404: it doesn't have this piece yet. Normal in a swarm, so it carries no penalty."""
    pass


async def _request(host, port, path, timeout, range_start=None, range_end=None,
                   response_timeout=None, *, access=None, existing=None, keep_alive=False):
    """Open a GET, return (status, headers, reader, writer) with the body not yet read."""
    response_timeout = timeout if response_timeout is None else response_timeout
    if existing is None:
        connect = access.connect if access else asyncio.open_connection
        reader, writer = await asyncio.wait_for(connect(host, port), timeout)
    else:
        reader, writer = existing
    try:
        req = f"GET {path} HTTP/1.0\r\n"
        if range_start is not None:
            end = "" if range_end is None else str(range_end)
            req += f"Range: bytes={range_start}-{end}\r\n"
        if keep_alive:
            req += "Connection: keep-alive\r\n"
        writer.write(req.encode() + (access.authorization_header if access else b"") + b"\r\n")
        await writer.drain()
        status_line = (await asyncio.wait_for(reader.readline(), response_timeout)).decode("latin-1").split()
        if len(status_line) < 2:
            raise _HttpError("bad response")
        headers = {}
        for _ in range(100):
            h = (await asyncio.wait_for(reader.readline(), response_timeout)).decode("latin-1")
            if h in ("\r\n", "\n", ""):
                break
            k, _, v = h.partition(":")
            headers[k.strip().lower()] = v.strip()
        return int(status_line[1]), headers, reader, writer
    except BaseException:
        writer.close()
        raise


async def fetch_index(host, port, pub_b64, game_id, timeout=10.0,
                      response_timeout=INDEX_BUILD_TIMEOUT, *, access=None,
                      on_progress=None) -> list[dict]:
    """Poll the Host's shared index job, then verify the signed result."""
    token = ''
    failures = 0
    expired_jobs = 0
    deadline = time.monotonic() + 1800
    while time.monotonic() < deadline:
        writer = None
        try:
            path = f'/index-job/{quote(game_id)}' + (f'?job={token}' if token else '')
            status, headers, reader, writer = await _request(
                host, port, path, timeout, response_timeout=min(timeout, 30),
                **({'access': access} if access else {}))
            if status == 404 and not token:
                return await _fetch_index_legacy(host, port, pub_b64, game_id, timeout,
                                                 response_timeout, access=access)
            if status == 404 and token:
                expired_jobs += 1
                if expired_jobs > 3:
                    raise _HttpError('Host repeatedly expired its game index job. Retry when Host indexing is less busy.')
                token = ''
                await asyncio.sleep(.25)
                continue
            length = int(headers.get('content-length', '-1'))
            if not 0 <= length <= MAX_INDEX_BYTES:
                raise _HttpError('bad index response length')
            body = await asyncio.wait_for(reader.readexactly(length), response_timeout)
            if status == 200:
                return _verify_index(body, pub_b64, game_id)
            status_data = json.loads(body)
            if status == 500:
                raise _HttpError('Host indexing failed: ' + str(status_data.get('error') or 'unknown error'))
            if status != 202 or status_data.get('state') != 'running':
                raise _HttpError(f'index job HTTP {status}')
            returned = status_data.get('id', '')
            if not isinstance(returned, str) or len(returned) != 32:
                raise _HttpError('invalid Host index job ID')
            token = returned
            failures = 0
            if on_progress:
                on_progress(status_data)
            await asyncio.sleep(.75)
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            failures += 1
            if failures >= 10:
                raise _HttpError('Lost contact with the Host while checking its game index.') from None
            await asyncio.sleep(min(failures, 3))
        finally:
            if writer:
                writer.close()
    raise _HttpError('Host indexing exceeded 30 minutes. Recheck this game on the Host.')


def _verify_index(body, pub_b64, game_id):
    idx = json.loads(body)
    if not verify_obj(pub_b64, idx):
        raise _HttpError('index signature invalid')
    try:
        FRESHNESS.check(pub_b64, f'index/{game_id}', idx)
    except StaleError as exc:
        raise _HttpError(f'index rejected: {exc}') from None
    return validate_index(idx, game_id)


async def _fetch_index_legacy(host, port, pub_b64, game_id, timeout, response_timeout, *, access=None):
    """Compatibility with a Host running a release before tracked index jobs."""
    last_error = None
    for attempt in range(3):
        writer = None
        try:
            status, headers, reader, writer = await _request(
                host, port, f"/index/{quote(game_id)}", timeout,
                response_timeout=response_timeout, **({"access": access} if access else {}))
            if status != 200:
                raise _HttpError(f"index HTTP {status}")
            n = int(headers.get("content-length", "-1"))
            if not 0 <= n <= MAX_INDEX_BYTES:
                raise _HttpError("bad index length")
            body = await asyncio.wait_for(reader.readexactly(n), response_timeout)
            break
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError) as exc:
            last_error = exc
            if attempt == 2:
                raise
            await asyncio.sleep(0.5 * (attempt + 1))
        finally:
            if writer:
                writer.close()
    else:
        raise last_error or _HttpError("couldn't download the Host's game index")
    return _verify_index(body, pub_b64, game_id)


async def fetch_art(host, port, game_id, expected_sha256, dest_path, timeout=10.0, kind="", *,
                    access=None) -> bool:
    """Fetch an image whose hash was covered by the Host's signed library listing.

    kind "" is the exe icon (legacy /art/<id> route); kind "portrait" is the cover.
    """
    dest = Path(dest_path)
    try:
        if dest.is_file() and hashlib.sha256(dest.read_bytes()).hexdigest() == expected_sha256:
            return True
        status, headers, reader, writer = await _request(
            host, port, f"/art/{quote(game_id)}" + ("/portrait" if kind == "portrait" else ""), timeout,
            **({"access": access} if access else {}))
        try:
            if status != 200:
                return False
            length = int(headers.get("content-length", "-1"))
            if not 0 <= length <= 12 * 1024 * 1024:
                return False
            data = await asyncio.wait_for(reader.readexactly(length), timeout)
        finally:
            writer.close()
        if hashlib.sha256(data).hexdigest() != expected_sha256:
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_bytes(data)
        replace_file(tmp, dest)
        return True
    except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError):
        return False


def _write_hash(f, hasher, block):
    f.write(block)
    hasher.update(block)


async def _finish_disk_write(function, *args):
    """A paused transfer must finish its current disk write before resuming."""
    return await finish_disk_work(function, *args)


def _prefix_hash(path: Path, hasher, limit: int, *, cancelled=None):
    left = limit
    with open(path, "rb") as f:
        while left:
            check_cancelled(cancelled)
            block = f.read(min(CHUNK, left))
            if not block:
                break
            hasher.update(block)
            left -= len(block)


async def _download(host, port, game_id, entry, dest: Path, timeout, on_bytes, result: SyncResult, *,
                    access=None):
    final = safe_join(dest, entry["path"])
    final.parent.mkdir(parents=True, exist_ok=True)
    part = final.with_name(final.name + PART_SUFFIX)
    size, want = entry["size"], entry["sha256"]
    pieces = entry.get("pieces")
    if pieces is not None:
        scheduler = result._scheduler
        had_partial = part.exists() and part.stat().st_size > 0
        if part.exists() and part.stat().st_size > size:
            part.unlink()
            _discard_journal(part)
            had_partial = False
        with open(part, "r+b" if part.exists() else "w+b") as f:
            f.truncate(size)
        verified = _load_journal(part, size, want, len(pieces)) or set()
        journal_lock = asyncio.Lock()
        pending = [0]
        last_checkpoint = [time.monotonic()]

        async def checkpoint(index=None, *, force=False):
            async with journal_lock:
                if index is not None and index not in verified:
                    verified.add(index)
                    pending[0] += 1
                if not pending[0] or (not force and pending[0] < 16 and
                                      time.monotonic() - last_checkpoint[0] < 3):
                    return
                last_checkpoint[0] = time.monotonic()
                try:
                    await finish_disk_work(_save_journal, part, size, want, len(pieces), verified.copy())
                except OSError:
                    # The journal is an optimization. The partial file can be rehashed safely.
                    return
                pending[0] = 0

        async def piece(piece_index, session, trust_journal=True, report=True):
            start = piece_index * CHUNK
            length = min(CHUNK, size - start)
            expected_hash = pieces[piece_index]
            if trust_journal and piece_index in verified:
                if report:
                    on_bytes(length)
                if result._on_piece:
                    await result._on_piece(game_id, dest, entry, piece_index)
                return
            def read_existing():
                with part.open('rb') as stream:
                    stream.seek(start)
                    return stream.read(length)
            existing = await finish_disk_work(read_existing)
            if hashlib.sha256(existing).hexdigest() == expected_hash:
                await checkpoint(piece_index)
                if report:
                    on_bytes(length)
                if result._on_piece:
                    await result._on_piece(game_id, dest, entry, piece_index)
                return
            errors = []
            lacking = {}  # Missing pieces can arrive at a peer while this download is running.
            retry_until = time.monotonic() + 90
            attempt = 0
            while True:
                transient = False
                sources = result._live_sources() + [(host, port, False)]
                for source in scheduler.order(sources, piece_index):
                    source_host, source_port, is_peer = source
                    if lacking.get(source, 0) > time.monotonic():
                        transient = True
                        continue
                    if scheduler.sources.get(source, (0,0,0))[2] > time.monotonic() and is_peer:
                        continue
                    if session.get('source') != source:
                        old = session.pop('writer', None)
                        if old:
                            old.close()
                        session.clear()
                    writer = None
                    retain = False
                    async with scheduler:
                        started = time.monotonic()
                        try:
                            route = 'piece' if is_peer else 'file'
                            url = f"/{route}/{quote(game_id)}/{quote(entry['path'])}"
                            existing = ((session['reader'], session['writer'])
                                        if session.get('source') == source and not session['writer'].is_closing()
                                        else None)
                            request_options = {"access": access} if access and not is_peer else {}
                            try:
                                status, headers, reader, writer = await _request(
                                    source_host, source_port, url, timeout, start, start + length - 1,
                                    existing=existing, keep_alive=True, **request_options)
                            except (_HttpError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                                if existing is None:
                                    raise
                                session['writer'].close()
                                session.clear()
                                status, headers, reader, writer = await _request(
                                    source_host, source_port, url, timeout, start, start + length - 1,
                                    keep_alive=True, **request_options)
                            if is_peer and status == 503:
                                raise _PeerPaused()
                            if is_peer and status == 404:
                                raise _PeerLacksPiece()
                            if status != 206 or int(headers.get('content-length', '-1')) != length:
                                raise _HttpError(f'piece HTTP {status}')
                            try:
                                block = await asyncio.wait_for(reader.readexactly(length), timeout)
                            except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
                                if existing is None:
                                    raise
                                writer.close()
                                session.clear()
                                status, headers, reader, writer = await _request(
                                    source_host, source_port, url, timeout, start, start + length - 1,
                                    keep_alive=True, **request_options)
                                if status != 206 or int(headers.get('content-length', '-1')) != length:
                                    raise _HttpError(f'piece HTTP {status}')
                                block = await asyncio.wait_for(reader.readexactly(length), timeout)
                            if hashlib.sha256(block).hexdigest() != expected_hash:
                                raise _HttpError('piece sha256 mismatch')
                            def store():
                                with part.open('r+b') as stream:
                                    stream.seek(start)
                                    stream.write(block)
                                    stream.flush()
                            await _finish_disk_write(store)
                            await checkpoint(piece_index)
                            scheduler.success(source, length, time.monotonic()-started)
                            log.debug("piece %d of %s from %s:%s", piece_index, entry["path"], source_host, source_port)
                            result.bytes_downloaded += length
                            result._received.record(f"{source_host}:{source_port}", game_id, length)
                            if report:
                                on_bytes(length)
                            if result._on_piece:
                                await result._on_piece(game_id, dest, entry, piece_index)
                            if (headers.get('connection', '').lower() == 'keep-alive'
                                    and not writer.is_closing() and session.get('count', 0) < 63):
                                session.update(source=source, reader=reader, writer=writer,
                                               count=session.get('count', 0) + 1)
                                retain = True
                            return
                        except _PeerPaused:
                            transient = True
                            # Back off without a failure penalty; log once per cooldown, not once per piece.
                            if scheduler.defer(source, 2):
                                log.info("peer %s:%s is paused; trying another source", source_host, source_port)
                            else:
                                log.debug("peer %s:%s still paused (piece %d of %s)", source_host, source_port, piece_index, entry["path"])
                            continue
                        except _PeerLacksPiece:
                            lacking[source] = time.monotonic() + PEER_LACKS_RETRY_DELAY
                            transient = True
                            if scheduler.first(("lacks", source, entry["path"])):
                                log.info("peer %s:%s lacks piece %d of %s", source_host, source_port, piece_index, entry["path"])
                            else:
                                log.debug("peer %s:%s lacks piece %d of %s", source_host, source_port, piece_index, entry["path"])
                            continue
                        except (_HttpError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError) as exc:
                            if isinstance(exc, (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError)):
                                transient = True
                            scheduler.failure(source)
                            errors.append(str(exc))
                            log.info("source %s:%s failed piece %d of %s: %s", source_host, source_port, piece_index, entry["path"], exc)
                        finally:
                            if writer and not retain:
                                writer.close()
                                if session.get('writer') is writer:
                                    session.clear()
                attempt += 1
                if attempt >= 3 and (not transient or time.monotonic() >= retry_until):
                    raise _HttpError(errors[-1] if errors else 'No source available')
                await asyncio.sleep(min(5, .5 * attempt))
        async def run_workers(trust_journal=True, report=True):
            # Bounded workers: large archives never create one task per piece.
            remaining = iter(range(len(pieces)))
            async def worker():
                session = {}
                try:
                    for index in remaining:
                        await piece(index, session, trust_journal, report)
                finally:
                    writer = session.get('writer')
                    if writer:
                        writer.close()
            workers = [asyncio.create_task(worker()) for _ in range(min(scheduler.maximum, len(pieces)))]
            try:
                await asyncio.gather(*workers)
            finally:
                for task in workers:
                    if not task.done() and not task.cancelling():
                        task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
                await checkpoint(force=True)

        await run_workers()
        if had_partial:
            result.resumed.append(entry["path"])
        if await run_hash_work(hash_file, part) != want:
            # A stale or externally modified journal can skip bad bytes. Rehash
            # every piece and repair only mismatches before rejecting the file.
            verified.clear()
            _discard_journal(part)
            await run_workers(trust_journal=False, report=False)
            if await run_hash_work(hash_file, part) != want:
                part.unlink(missing_ok=True)
                _discard_journal(part)
                raise _HttpError("sha256 mismatch (file changed on host or was tampered with)")
        await finish_disk_work(replace_file, part, final)
        _discard_journal(part)
        return
    offset = part.stat().st_size if part.exists() else 0
    if offset > size:
        part.unlink()
        offset = 0
    hasher = hashlib.sha256()
    if offset:
        await run_hash_work(_prefix_hash, part, hasher, offset)
        on_bytes(offset)
        result.resumed.append(entry["path"])
    if offset < size or size == 0:
        url = f"/file/{quote(game_id)}/{quote(entry['path'])}"
        status, headers, reader, writer = await _request(
            host, port, url, timeout, range_start=offset or None,
            **({"access": access} if access else {}))
        try:
            if status == 200 and offset:                 # server ignored Range: restart from zero
                on_bytes(-offset)
                offset, hasher = 0, hashlib.sha256()
            elif status not in (200, 206):
                raise _HttpError(f"HTTP {status}")
            with open(part, "r+b" if offset else "wb") as f:
                f.seek(offset)
                f.truncate()
                got = offset
                while True:
                    block = await asyncio.wait_for(reader.read(CHUNK), timeout)
                    if not block:
                        break
                    await _finish_disk_write(_write_hash, f, hasher, block)
                    got += len(block)
                    result.bytes_downloaded += len(block)
                    result._received.record(f"{host}:{port}", game_id, len(block))
                    on_bytes(len(block))
        finally:
            writer.close()
        if got != size:
            raise _HttpError(f"short or long download ({got} of {size} bytes)")
    if hasher.hexdigest() != want:
        part.unlink(missing_ok=True)
        raise _HttpError("sha256 mismatch (file changed on host or was tampered with)")
    await finish_disk_work(replace_file, part, final)


def _journal_path(part: Path) -> Path:
    # The suffix makes the journal an internal file, excluded from game indexes.
    return part.with_name(part.name + '.resume' + PART_SUFFIX)


def _discard_journal(part: Path) -> None:
    try:
        _journal_path(part).unlink(missing_ok=True)
    except OSError:
        pass  # This metadata must never turn an installed file into a failed transfer.


def _load_journal(part: Path, size: int, sha256: str, count: int) -> set[int] | None:
    if not part.is_file() or part.stat().st_size != size:
        return None
    try:
        record = json.loads(_journal_path(part).read_text(encoding='utf-8'))
        indexes = record['verified']
        if (record.get('version') != 1 or record.get('size') != size or
                record.get('sha256') != sha256 or record.get('count') != count or
                not isinstance(indexes, list) or
                any(type(index) is not int or index < 0 or index >= count for index in indexes)):
            return None
        return set(indexes)
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _save_journal(part: Path, size: int, sha256: str, count: int, verified: set[int]) -> None:
    """Make piece data durable before publishing a compact atomic checkpoint."""
    journal = _journal_path(part)
    temporary = journal.with_name(journal.name + '.tmp' + PART_SUFFIX)
    with part.open('r+b') as stream:
        stream.flush()
        os.fsync(stream.fileno())
    payload = {'version': 1, 'size': size, 'sha256': sha256,
               'count': count, 'verified': sorted(verified)}
    try:
        with temporary.open('w', encoding='utf-8') as stream:
            json.dump(payload, stream, separators=(',', ':'))
            stream.flush()
            os.fsync(stream.fileno())
        replace_file(temporary, journal)
    finally:
        temporary.unlink(missing_ok=True)


def _verified_partial_bytes(path: Path, size: int, pieces: list[str], sha256: str = '', *, cancelled=None) -> int:
    """Count reusable piece bytes in a preallocated partial file."""
    if not path.is_file() or path.stat().st_size > size:
        return 0
    recorded = _load_journal(path, size, sha256, len(pieces)) if sha256 else None
    if recorded is not None:
        return sum(min(CHUNK, size - index * CHUNK) for index in recorded)
    reusable = 0
    with path.open("rb") as stream:
        for index, expected in enumerate(pieces):
            check_cancelled(cancelled)
            length = min(CHUNK, size - index * CHUNK)
            stream.seek(index * CHUNK)
            block = stream.read(length)
            if len(block) == length and hashlib.sha256(block).hexdigest() == expected:
                reusable += length
    return reusable


def _allocated_partial_bytes(path: Path, size: int, *, cancelled=None) -> int:
    """Storage already charged to free space, independent of verified progress.

    Sparse/compressed files must contribute their physical allocation rather
    than logical length. An unavailable measurement conservatively contributes
    nothing; an oversized partial will be removed by _download.
    """
    check_cancelled(cancelled)
    try:
        if path.is_symlink() or not path.is_file():
            return 0
        stat = path.stat()
        if stat.st_size > size:
            return 0
        if hasattr(stat, 'st_blocks'):
            allocated = stat.st_blocks * 512
        elif os.name == 'nt':
            import ctypes
            from ctypes import wintypes
            kernel = ctypes.WinDLL('kernel32', use_last_error=True)
            get_size = kernel.GetCompressedFileSizeW
            get_size.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD)]
            get_size.restype = wintypes.DWORD
            high = wintypes.DWORD()
            ctypes.set_last_error(0)
            low = get_size(str(path.resolve()), ctypes.byref(high))
            if low == 0xffffffff and ctypes.get_last_error():
                return 0
            allocated = (high.value << 32) | low
        else:
            return 0
        return max(0, min(size, stat.st_size, allocated))
    except OSError:
        return 0


def _prune(dest: Path, keep: set[str]) -> list[str]:
    removed = []
    for dirpath, _, names in os.walk(dest, topdown=False):
        for n in names:
            p = Path(dirpath) / n
            rel = p.relative_to(dest).as_posix()
            if rel not in keep and not is_internal(n):
                p.unlink()
                removed.append(rel)
        if Path(dirpath) != dest and not any(Path(dirpath).iterdir()):
            Path(dirpath).rmdir()
    return removed


async def sync_game(host, port, pub_b64, game_id, dest_dir, progress=None, prune=False, verify=False,
                    concurrency=12, timeout=15.0, min_free_bytes=0, peers=None, on_index=None, on_piece=None,
                    control=None, received=None, index_progress=None, *, access=None, held_index=None) -> SyncResult:
    total_before_pause = 0
    def report(done, total, path):
        nonlocal total_before_pause
        total_before_pause = max(total_before_pause, total)
        if progress:
            progress(total_before_pause-total+done, total_before_pause, path)
    # A caller may retain this across bounded reconnect attempts. Only fetch_index
    # places signature-verified entries here; an invalid response never replaces it.
    if held_index is None:
        held_index = {}
    def attempt():
        return _sync_game_once(host, port, pub_b64, game_id, dest_dir, report, prune, verify,
                               concurrency, timeout, min_free_bytes, peers, on_index, on_piece, held_index, received,
                               index_progress=index_progress, **({"access": access} if access else {}))
    return await control.run(attempt) if control else await attempt()


async def _sync_game_once(host, port, pub_b64, game_id, dest_dir, progress=None, prune=False, verify=False,
                          concurrency=12, timeout=15.0, min_free_bytes=0, peers=None, on_index=None, on_piece=None,
                          held_index=None, received=None, index_progress=None, *, access=None) -> SyncResult:
    """Bring dest_dir in line with the host's signed index. Never raises for network/verification problems;
    inspect SyncResult.ok / .error / .failed. progress(bytes_done, bytes_total, current_path) is called as data arrives."""
    res = SyncResult()
    auth = {"access": access} if access else {}
    def live_sources():
        available = peers() if callable(peers) else (peers or [])
        out = []
        for peer in available:
            try:
                if game_id in peer.get('games', []) and peer.get('host') and 1 <= int(peer.get('port', 0)) <= 65535:
                    out.append((str(peer['host']), int(peer['port']), True))
            except (ValueError, TypeError, AttributeError):
                continue
        return out
    res._live_sources = live_sources
    res._scheduler = Scheduler(concurrency)
    res._on_piece = on_piece
    if received is not None:
        res._received = received  # shared across pause/resume attempts so the Downloads page keeps its totals
    dest = Path(dest_dir)
    try:
        try:
            files = await fetch_index(host, port, pub_b64, game_id, timeout,
                                      on_progress=index_progress, **auth)
            if held_index is not None:
                held_index['files'] = files
        except _HttpError as exc:
            # Only fall back for a transient connection loss. Signature,
            # freshness, HTTP and Host indexing errors must remain visible.
            if "Lost contact with the Host" not in str(exc) or not held_index or 'files' not in held_index:
                raise
            files = held_index['files']
        except (OSError, asyncio.TimeoutError, asyncio.IncompleteReadError):
            # Host unreachable on resume after a pause: continue from the index verified earlier (peers may still serve pieces).
            if not held_index or 'files' not in held_index:
                raise
            files = held_index['files']
        dest.mkdir(parents=True, exist_ok=True)
        if on_index:
            await on_index(game_id, dest, files)
        cache = HashCache(dest / CACHE_NAME)
        need, same = await run_hash_work(diff_index, files, dest, cache, verify)
        res.skipped = [f["path"] for f in same]
        total = sum(f["size"] for f in need)
        # Existing allocation already reduced disk_usage.free. Even corrupt
        # ranges can be overwritten in place; sparse holes still need space.
        already = 0
        for entry in need:
            final = safe_join(dest, entry['path'])
            part = final.with_name(final.name + PART_SUFFIX)
            already += await run_hash_work(_allocated_partial_bytes, part, entry['size'])
        free = shutil.disk_usage(dest).free
        if total - already + min_free_bytes > free:
            res.error = f"not enough disk space: need {total - already + min_free_bytes} bytes, {free} free"
            return res
        done = 0
        current = [""]

        def on_bytes(n):
            nonlocal done
            done += n
            if progress:
                progress(done, total, current[0])

        sem = asyncio.Semaphore(max(1, min(4, concurrency)))
        save_lock = asyncio.Lock()
        last_save = [time.monotonic()]

        async def save_cache(force=False):
            # Persist verified-file hashes as files complete so a pause/cancel does not force a full re-hash on resume.
            if not force and time.monotonic() - last_save[0] < 3.0:
                return
            async with save_lock:
                last_save[0] = time.monotonic()
                try:
                    await finish_disk_work(cache.save)
                except OSError:
                    pass  # the hash cache only saves re-hashing; a failed save must not fail the sync

        async def one(entry):
            async with sem:
                current[0] = entry["path"]
                try:
                    await _download(host, port, game_id, entry, dest, timeout, on_bytes, res, **auth)
                except (_HttpError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError) as e:
                    res.failed.append((entry["path"], str(e) or type(e).__name__))
                    return
                st = safe_join(dest, entry["path"]).stat()
                cache.put(entry["path"], st, entry["sha256"])
                res.downloaded.append(entry["path"])
                await save_cache()
                if entry["size"] == 0 and res._on_piece:
                    # Zero-byte files have no pieces, so nothing else announces them before the sync ends.
                    await res._on_piece(game_id, dest, entry, 0)

        pending_files = iter(need)
        async def file_worker():
            for entry in pending_files:
                await one(entry)
        workers = [asyncio.create_task(file_worker()) for _ in range(min(4, len(need)))]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            await save_cache(force=True)  # pause/cancel: keep what was verified so far
            raise
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        if prune and not res.failed:
            res.pruned = await asyncio.to_thread(_prune, dest, {f["path"] for f in files})
        try:
            await finish_disk_work(cache.save)
        except OSError:
            pass  # the hash cache only saves re-hashing; a failed save must not fail the sync
        res.ok = not res.failed
        if res.ok:
            res.verified_files[game_id] = [f["path"] for f in files]
        if res.failed:
            res.error = f"{len(res.failed)} file(s) failed"
    except (_HttpError, OSError, asyncio.TimeoutError, asyncio.IncompleteReadError, ValueError, KeyError) as e:
        res.error = str(e) or type(e).__name__
    return res
