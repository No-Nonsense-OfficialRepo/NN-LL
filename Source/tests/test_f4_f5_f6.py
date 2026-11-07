import asyncio, base64, json, time
from lantool.trust import signing as S
from lantool.trust.planet_transport import PlanetServer, fetch_planet
from lantool.presence.watcher import ProcessWatcher
from lantool.ui.viewmodel import LibraryViewModel


async def _serve(tmp_path, priv, planet=b"PLANET-V2" * 100):
    p = tmp_path / "planet"; p.write_bytes(planet)
    srv = PlanetServer(priv, p, host="127.0.0.1", port=0); await srv.start()
    return srv, planet


async def test_f4_stale_client_gets_valid_planet(tmp_path):
    priv, pub = S.generate_keypair()
    srv, planet = await _serve(tmp_path, priv)
    dest = tmp_path / "client_planet"; dest.write_bytes(b"old")
    assert await fetch_planet("127.0.0.1", srv.port, pub, S.sha256_hex(planet), dest)
    assert dest.read_bytes() == planet
    await srv.stop()


async def test_f4_wrong_key_or_hash_rejected_and_old_file_kept(tmp_path):
    priv, pub = S.generate_keypair()
    _, other_pub = S.generate_keypair()
    srv, planet = await _serve(tmp_path, priv)
    dest = tmp_path / "client_planet"; dest.write_bytes(b"old")
    assert not await fetch_planet("127.0.0.1", srv.port, other_pub, S.sha256_hex(planet), dest)   # wrong key
    assert not await fetch_planet("127.0.0.1", srv.port, pub, S.sha256_hex(b"different"), dest)   # hash != beacon
    assert dest.read_bytes() == b"old"
    await srv.stop()


async def test_f4_tampered_payload_rejected(tmp_path):
    priv, pub = S.generate_keypair()
    good = b"PLANET" * 50
    pkg = S.sign_planet(priv, good)
    evil = b"EVIL" * 50
    body = json.dumps({**pkg, "data": base64.b64encode(evil).decode()}).encode()

    async def h(r, w):
        await r.readuntil(b"\r\n\r\n")
        w.write(b"HTTP/1.0 200 OK\r\n\r\n" + body); await w.drain(); w.close()
    srv = await asyncio.start_server(h, "127.0.0.1", 0)
    port = srv.sockets[0].getsockname()[1]
    dest = tmp_path / "p"
    # attacker also matches the beacon hash to the evil file; signature check must still fail
    assert not await fetch_planet("127.0.0.1", port, pub, S.sha256_hex(evil), dest)
    assert not dest.exists()
    srv.close()


async def test_f4_unreachable_host_returns_false(tmp_path):
    assert not await fetch_planet("127.0.0.1", 1, "x", "y", tmp_path / "p", timeout=1)


async def test_f5_watcher_launch_exit_debounce():
    procs, events = set(), []
    w = ProcessWatcher({"g": "Game.EXE"}, lambda g: events.append(("launch", g)),
                       lambda g: events.append(("exit", g)), list_fn=lambda: set(procs), miss_limit=2)
    await w.poll_once(); assert events == []
    procs.add("game.exe"); await w.poll_once(); await w.poll_once()
    assert events == [("launch", "g")]
    procs.clear(); await w.poll_once()          # one miss: launcher re-spawn tolerated
    assert events == [("launch", "g")]
    procs.add("game.exe"); await w.poll_once(); procs.clear()
    await w.poll_once(); await w.poll_once()
    assert events == [("launch", "g"), ("exit", "g")]


def test_f6_viewmodel_30_games_badges_and_diff(tmp_path):
    lib = {f"g{i}": {"id": f"g{i}", "name": f"Game {i:02d}", "exe": "x.exe", "install_dir": str(tmp_path)}
           for i in range(30)}
    (tmp_path / "x.exe").write_bytes(b"")
    vm = LibraryViewModel(lib)
    t0 = time.perf_counter()
    changed = vm.update_counts({"games": {"g3": {"hovering": 10, "playing": 0}}, "players": 10})
    tiles = vm.tiles()
    assert time.perf_counter() - t0 < 0.05
    assert changed == {"g3"} and len(tiles) == 30
    assert vm.tile("g3").badge == "" and vm.tile("g3").installed  # hover counts intentionally omitted
    assert vm.update_counts({"games": {"g3": {"hovering": 10, "playing": 0}}, "players": 10}) == set()
    assert vm.update_counts({"games": {"g3": {"hovering": 0, "playing": 2}}, "players": 2}) == {"g3"}
    assert vm.tile("g3").badge == "\U0001F3AE 2 playing"
    assert [t.id for t in vm.tiles("game 07")] == ["g7"]
