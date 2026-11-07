"""F8 acceptance: hash-diff sync, resume, verification, tamper/forgery/traversal rejection."""
import asyncio, os, json, hashlib
import pytest
from lantool.trust.signing import generate_keypair, sign_obj
from lantool.filesync.server import FileSyncServer
from lantool.filesync.client import sync_game, fetch_index, _journal_path, _save_journal, _verified_partial_bytes
from lantool.filesync.index import CHUNK, PART_SUFFIX, CACHE_NAME, PathError, safe_rel, safe_join, build_index


def make_game(lib, gid="bfbc2", n_small=20, big=3 * 1024 * 1024):
    g = lib / gid
    (g / "data").mkdir(parents=True)
    (g / "game.exe").write_bytes(b"MZ" + os.urandom(2000))
    (g / "data" / "big.bin").write_bytes(os.urandom(big))
    for i in range(n_small):
        (g / "data" / f"f{i:03d}.dat").write_bytes(os.urandom(500 + i))
    (g / "empty.txt").write_bytes(b"")
    return g


async def host(tmp_path, **kw):
    priv, pub = generate_keypair()
    lib = tmp_path / "lib"
    g = make_game(lib, **kw)
    srv = FileSyncServer(priv, lib, host="127.0.0.1", port=0)
    await srv.start()
    return srv, priv, pub, g


def tree(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob("*") if p.is_file() and not p.name.endswith(PART_SUFFIX) and p.name != CACHE_NAME}


async def test_f8_full_sync_then_only_changed_file_redownloaded(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    dest = tmp_path / "client"
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)
    assert r.ok, r.error
    assert tree(dest) == tree(g) and len(r.downloaded) == 23

    srv.requests.clear()
    r2 = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)          # nothing changed
    assert r2.ok and r2.downloaded == [] and len(r2.skipped) == 23
    assert [q for q in srv.requests if q[0].startswith("file/")] == []        # no file request at all

    (g / "data" / "f005.dat").write_bytes(b"patched on host")                 # host patches one file
    srv.requests.clear()
    r3 = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)
    assert r3.ok and r3.downloaded == ["data/f005.dat"]
    assert [q[0] for q in srv.requests if q[0].startswith("file/")] == ["file/bfbc2/data/f005.dat"]
    assert tree(dest) == tree(g)
    await srv.stop()


async def test_f8_resume_continues_from_partial_file(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    dest = tmp_path / "client"
    (dest / "data").mkdir(parents=True)
    big = (g / "data" / "big.bin").read_bytes()
    cut = 1024 * 1024
    (dest / "data" / ("big.bin" + PART_SUFFIX)).write_bytes(big[:cut])        # interrupted earlier download
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)
    assert r.ok and "data/big.bin" in r.resumed
    big_req = [q for q in srv.requests if q[0].endswith("big.bin")]
    assert sum(q[2] for q in big_req) == len(big) - cut
    assert all(q[1] >= cut for q in big_req)  # Verified pieces are never resent.
    assert (dest / "data" / "big.bin").read_bytes() == big
    assert not list(dest.rglob("*" + PART_SUFFIX))
    await srv.stop()


async def test_f8_corrupt_partial_is_repaired_before_install(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    dest = tmp_path / "client"
    (dest / "data").mkdir(parents=True)
    (dest / "data" / ("big.bin" + PART_SUFFIX)).write_bytes(b"\x00" * 5000)   # garbage prefix
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)
    assert r.ok
    assert (dest / "data" / "big.bin").read_bytes() == (g / "data" / "big.bin").read_bytes()
    r2 = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)           # part was removed -> clean retry works
    assert r2.ok and tree(dest) == tree(g)
    await srv.stop()


async def test_verified_piece_journal_survives_restart_and_repairs_stale_bytes(tmp_path):
    srv, _, pub, game = await host(tmp_path, n_small=0, big=2 * CHUNK + 7)
    entry = next(f for f in build_index('bfbc2', game)['files'] if f['path'] == 'data/big.bin')
    data = (game / 'data' / 'big.bin').read_bytes()
    try:
        dest = tmp_path / 'resume'
        (dest / 'data').mkdir(parents=True)
        part = dest / 'data' / ('big.bin' + PART_SUFFIX)
        part.write_bytes(data[:CHUNK] + bytes(len(data) - CHUNK))
        _save_journal(part, len(data), entry['sha256'], len(entry['pieces']), {0})
        assert _verified_partial_bytes(part, len(data), entry['pieces'], entry['sha256']) == CHUNK
        result = await sync_game('127.0.0.1', srv.port, pub, 'bfbc2', dest)
        assert result.ok, result.error
        assert (dest / 'data' / 'big.bin').read_bytes() == data
        assert not _journal_path(part).exists()
        assert all(start >= CHUNK for route, start, _ in srv.requests if route.endswith('big.bin'))

        stale = tmp_path / 'stale'
        (stale / 'data').mkdir(parents=True)
        corrupt = stale / 'data' / ('big.bin' + PART_SUFFIX)
        corrupt.write_bytes(b'X' * CHUNK + data[CHUNK:])
        _save_journal(corrupt, len(data), entry['sha256'], len(entry['pieces']),
                      set(range(len(entry['pieces']))))
        # The checkpoint can be stale after external edits. The whole-file gate
        # must trigger a piece recheck and fetch only the damaged range.
        assert _verified_partial_bytes(corrupt, len(data), entry['pieces'], entry['sha256']) == len(data)
        srv.requests.clear()
        repaired = await sync_game('127.0.0.1', srv.port, pub, 'bfbc2', stale)
        assert repaired.ok, repaired.error
        assert (stale / 'data' / 'big.bin').read_bytes() == data
        assert not _journal_path(corrupt).exists()
        assert [start for route, start, _ in srv.requests if route.endswith('big.bin')] == [0]
    finally:
        await srv.stop()


async def test_f8_modified_local_file_is_repaired_and_verify_catches_same_size_edit(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    dest = tmp_path / "client"
    assert (await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)).ok
    exe = dest / "game.exe"
    original = exe.read_bytes()
    st = exe.stat()
    exe.write_bytes(b"XX" + original[2:])                                      # same size, corrupted
    os.utime(exe, ns=(st.st_atime_ns, st.st_mtime_ns))                         # same mtime: cache is fooled
    assert (await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)).downloaded == []   # documented cache limit
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest, verify=True)
    assert r.downloaded == ["game.exe"] and exe.read_bytes() == original
    await srv.stop()


async def test_f8_file_changed_on_host_after_index_is_rejected(tmp_path):
    srv, priv, pub, g = await host(tmp_path, n_small=1)
    files = await fetch_index("127.0.0.1", srv.port, pub, "bfbc2")           # client has the index...
    (g / "game.exe").write_bytes(b"MZ-EVIL" + b"\x00" * 1995)                 # ...then the served file differs (same size, 2002)
    from lantool.filesync import client as C
    res = C.SyncResult()
    entry = next(f for f in files if f["path"] == "game.exe")
    dest = tmp_path / "c"
    dest.mkdir()
    assert entry["size"] == 2002
    try:
        await C._download("127.0.0.1", srv.port, "bfbc2", entry, dest, 5, lambda n: None, res)
        raised = False
    except C._HttpError as e:
        raised = "sha256" in str(e)
    assert raised and not (dest / "game.exe").exists()
    await srv.stop()


async def test_f8_wrong_key_and_forged_index_rejected(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    _, other_pub = generate_keypair()
    r = await sync_game("127.0.0.1", srv.port, other_pub, "bfbc2", tmp_path / "c1")
    assert not r.ok and "signature" in r.error and not (tmp_path / "c1" / "game.exe").exists()
    await srv.stop()

    class Forger(FileSyncServer):                                              # edits a hash after signing
        async def signed_index(self, game_id):
            idx = await super().signed_index(game_id)
            idx["files"][0]["sha256"] = "0" * 64
            return idx
    f = Forger(priv, tmp_path / "lib", host="127.0.0.1", port=0)
    await f.start()
    r = await sync_game("127.0.0.1", f.port, pub, "bfbc2", tmp_path / "c2")
    assert not r.ok and "signature" in r.error
    await f.stop()


async def test_f8_signed_index_for_other_game_and_hostile_paths_rejected(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    make_game(tmp_path / "lib", "other", n_small=1)
    other = await srv.signed_index("other")

    class Swapper(FileSyncServer):                                             # serves game "other" index for any id
        async def signed_index(self, game_id):
            return other
    s = Swapper(priv, tmp_path / "lib", host="127.0.0.1", port=0)
    await s.start()
    r = await sync_game("127.0.0.1", s.port, pub, "bfbc2", tmp_path / "c")
    assert not r.ok and "different game" in r.error
    await s.stop()

    class Evil(FileSyncServer):                                                # validly signed but path escapes dest
        async def signed_index(self, game_id):
            return sign_obj(self.priv, {"game_id": game_id, "total_bytes": 1, "files": [
                {"path": "../../evil.exe", "size": 1, "sha256": "a" * 64}]})
    e = Evil(priv, tmp_path / "lib", host="127.0.0.1", port=0)
    await e.start()
    r = await sync_game("127.0.0.1", e.port, pub, "bfbc2", tmp_path / "c3")
    assert not r.ok and not (tmp_path / "evil.exe").exists()
    await e.stop()
    await srv.stop()


async def test_f8_server_refuses_traversal_and_internal_files(tmp_path):
    srv, priv, pub, g = await host(tmp_path)
    (tmp_path / "secret.txt").write_text("nope")
    (g / ("x.bin" + PART_SUFFIX)).write_bytes(b"partial")

    async def get(path):
        r, w = await asyncio.open_connection("127.0.0.1", srv.port)
        w.write(f"GET {path} HTTP/1.0\r\n\r\n".encode()); await w.drain()
        data = await r.read(); w.close()
        return data.split(b"\r\n")[0]
    for bad in ("/file/bfbc2/../../secret.txt", "/file/bfbc2/%2e%2e/%2e%2e/secret.txt", "/file/bfbc2/..%5C..%5Csecret.txt",
                "/file/..%2F/secret.txt", "/file/bfbc2/x.bin" + PART_SUFFIX, "/index/..", "/index/nope", "/other"):
        assert b" 404 " in await get(bad), bad
    assert b" 200 " in await get("/file/bfbc2/game.exe")
    await srv.stop()


def test_safe_rel_rules(tmp_path):
    for ok in ("a.txt", "dir/sub/file.bin", "Data/x y.dat"):
        assert safe_rel(ok) == ok
    for bad in ("", "/abs", "a/../b", "..", "a//b", "a\\b", "C:/x", "a/b:stream", "trail.", "sp ", "nul", "dir/COM1.txt", "a/./b"):
        with pytest.raises(PathError):
            safe_rel(bad)
    with pytest.raises(PathError):
        safe_join(tmp_path, "../x")


async def test_f8_prune_and_disk_space_preflight(tmp_path):
    srv, priv, pub, g = await host(tmp_path, n_small=2)
    dest = tmp_path / "client"
    assert (await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)).ok
    (dest / "stale" / "deep").mkdir(parents=True)
    (dest / "stale" / "deep" / "old.dll").write_bytes(b"old")
    (dest / "keepme.sav").write_bytes(b"save")
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)             # default: no prune
    assert r.ok and r.pruned == [] and (dest / "keepme.sav").exists()
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest, prune=True)
    assert sorted(r.pruned) == ["keepme.sav", "stale/deep/old.dll"] and not (dest / "stale").exists()
    assert (dest / CACHE_NAME).exists()                                         # cache survives prune

    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", tmp_path / "tiny", min_free_bytes=10 ** 15)
    assert not r.ok and "disk space" in r.error and not (tmp_path / "tiny" / "game.exe").exists()
    await srv.stop()


async def test_f8_progress_reports_totals_and_unreachable_host_is_clean_failure(tmp_path):
    srv, priv, pub, g = await host(tmp_path, n_small=3)
    seen = []
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", tmp_path / "c",
                        progress=lambda d, t, p: seen.append((d, t)))
    assert r.ok and seen and seen[-1][0] == seen[-1][1] == sum(len(p.read_bytes()) for p in g.rglob("*") if p.is_file())
    await srv.stop()
    r = await sync_game("127.0.0.1", 1, pub, "bfbc2", tmp_path / "c2", timeout=1)
    assert not r.ok and r.error


async def test_f8_many_files_parallel_and_cache_makes_resync_fast(tmp_path):
    srv, priv, pub, g = await host(tmp_path, n_small=300, big=8 * 1024 * 1024)
    dest = tmp_path / "client"
    r = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest, concurrency=8)
    assert r.ok and len(r.downloaded) == 303 and tree(dest) == tree(g)
    import time
    t = time.perf_counter()
    r2 = await sync_game("127.0.0.1", srv.port, pub, "bfbc2", dest)
    assert r2.ok and not r2.downloaded and time.perf_counter() - t < 2
    await srv.stop()
