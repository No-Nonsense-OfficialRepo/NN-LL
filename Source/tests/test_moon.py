import asyncio, json, os
from pathlib import Path
import pytest
from lantool.trust import signing as S
from lantool.trust.moon import build_moon, moon_filename, MoonError
from lantool.trust.planet_transport import PlanetServer, fetch_planet
from lantool.netcore.beacon import make_beacon, parse_beacon
from lantool.netcore.moon_sync import MoonSync
from silent_tunnel.moon import install_moon, current_moon_hash, moon_path

MOON_ID = "deadbeef01"
MOON_BYTES = b"\x7fMOON" * 40


def fake_idtool(calls):
    """Mimics zerotier-idtool: initmoon prints a spec, genmoon writes <16hex>.moon from moon.json."""
    def run(cmd, cwd):
        calls.append(cmd[1:])
        if cmd[1] == "initmoon":
            return 0, json.dumps({"id": MOON_ID, "objtype": "world", "roots": [{"identity": "x", "stableEndpoints": []}]}), ""
        if cmd[1] == "genmoon":
            spec = json.loads((Path(cwd) / "moon.json").read_text())
            (Path(cwd) / moon_filename(spec["id"])).write_bytes(MOON_BYTES + json.dumps(spec["roots"][0]["stableEndpoints"]).encode())
            return 0, "", ""
        return 1, "", "bad"
    return run


def _home(tmp_path):
    h = tmp_path / "zt"; h.mkdir(); (h / "identity.public").write_text("aaaaaaaaaa:0:pub")
    return h


def test_build_moon_puts_host_endpoint_in_file(tmp_path):
    calls = []
    m = build_moon(_home(tmp_path), ["192.168.1.20/9993"], runner=fake_idtool(calls), idtool=["idtool"])
    assert m.moon_id == MOON_ID and m.filename == "000000deadbeef01.moon"
    assert b"192.168.1.20/9993" in m.data and [c[0] for c in calls] == ["initmoon", "genmoon"]


def test_build_moon_errors(tmp_path):
    with pytest.raises(MoonError):
        build_moon(tmp_path, ["1.2.3.4/9993"], runner=fake_idtool([]), idtool=["i"])      # no identity.public
    with pytest.raises(MoonError):
        build_moon(_home(tmp_path / "x") if False else _home(tmp_path), [], idtool=["i"])  # no endpoints
    with pytest.raises(MoonError):
        moon_filename("../../evil")


def test_install_and_hash(tmp_path):
    home = tmp_path / "zt"
    assert current_moon_hash(MOON_ID, home) == ""
    install_moon(MOON_ID, MOON_BYTES, home, restart=False)
    assert moon_path(MOON_ID, home).read_bytes() == MOON_BYTES
    assert current_moon_hash(MOON_ID, home) == S.sha256_hex(MOON_BYTES)


def test_install_falls_back_to_elevated_copy(tmp_path, monkeypatch):
    got = []
    def deny(self, *a, **k): raise PermissionError
    monkeypatch.setattr(Path, "write_bytes", deny)
    install_moon(MOON_ID, MOON_BYTES, tmp_path, restart=False, elevated_copy=lambda d, t: got.append((d, t)))
    assert got and got[0][0] == MOON_BYTES and got[0][1].name == "000000deadbeef01.moon"


def test_beacon_carries_moon_id():
    priv, pub = S.generate_keypair()
    b = parse_beacon(make_beacon(priv, "n", "1.2.3.4", 47800, "h", "1", moon_id=MOON_ID), pub)
    assert b["moon_id"] == MOON_ID


async def _host(tmp_path, priv):
    p = tmp_path / "hostmoon"; p.write_bytes(MOON_BYTES)
    srv = PlanetServer(priv, p, host="127.0.0.1", port=0); await srv.start()
    return srv


async def test_client_gets_moon_after_one_reserve(tmp_path):
    priv, pub = S.generate_keypair()
    srv = await _host(tmp_path, priv)
    installed = []
    ms = MoonSync(pub, home=tmp_path / "c", state_file=tmp_path / "st.json",
                  installer=lambda i, d, h: installed.append((i, d)))
    b = {"host": "127.0.0.1", "planet_port": srv.port, "planet_hash": S.sha256_hex(MOON_BYTES), "moon_id": MOON_ID}
    assert ms.local_hash() == ""
    assert await ms.fetch_and_install(b)
    assert installed == [(MOON_ID, MOON_BYTES)]
    assert MoonSync(pub, state_file=tmp_path / "st.json").moon_id == MOON_ID      # remembered across restarts
    await srv.stop()


async def test_tampered_or_wrong_key_moon_rejected(tmp_path):
    priv, pub = S.generate_keypair(); _, other = S.generate_keypair()
    srv = await _host(tmp_path, priv)
    installed = []
    b = {"host": "127.0.0.1", "planet_port": srv.port, "planet_hash": S.sha256_hex(MOON_BYTES), "moon_id": MOON_ID}
    assert not await MoonSync(other, installer=lambda *a: installed.append(a)).fetch_and_install(b)     # wrong key
    assert not await MoonSync(pub, installer=lambda *a: installed.append(a)).fetch_and_install({**b, "planet_hash": "0" * 64})
    assert not await MoonSync(pub, installer=lambda *a: installed.append(a)).fetch_and_install({**b, "moon_id": "../x"})
    assert installed == []
    await srv.stop()


async def test_install_failure_returns_false(tmp_path):
    priv, pub = S.generate_keypair()
    srv = await _host(tmp_path, priv)
    def boom(*a): raise RuntimeError("UAC declined")
    b = {"host": "127.0.0.1", "planet_port": srv.port, "planet_hash": S.sha256_hex(MOON_BYTES), "moon_id": MOON_ID}
    ms = MoonSync(pub, installer=boom)
    assert not await ms.fetch_and_install(b) and ms.moon_id is None
    await srv.stop()
