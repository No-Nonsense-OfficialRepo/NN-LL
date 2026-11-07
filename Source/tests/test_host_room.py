import asyncio
from unittest.mock import patch
from lantool.netcore.discovery import DiscoveryResponder
from lantool.trust import signing as S
from lantool.trust.moon import MoonFile
from lantool.trust.planet_transport import fetch_planet
from lantool.netcore.beacon import parse_beacon
from lantool.netcore.host_room import HostRoom


def _build_factory(calls):
    def build(home, endpoints):
        calls.append(endpoints)
        return MoonFile("deadbeef01", b"MOON:" + endpoints[0].encode())
    return build


async def test_host_serves_moon_and_rebuilds_on_ip_change(tmp_path):
    priv, pub = S.generate_keypair()
    ip, calls = ["192.168.1.20"], []
    h = HostRoom(priv, tmp_path, tmp_path / "w", "abcdef0123456789", lambda: ip[0], "1.0",
                 build=_build_factory(calls), planet_port=0, serve_host="127.0.0.1",
                 beacon_target="127.0.0.1", beacon_port=47999, recheck_s=0.05)
    # Keep real UDP discovery, but do not reserve the production host port.
    # Other launcher tests or an open Host may already own that fixed port.
    start_responder = DiscoveryResponder.start
    with patch.object(DiscoveryResponder, 'start',
                      side_effect=lambda payload: start_responder(payload, host='127.0.0.1', port=0)):
        await h.start()
    b = parse_beacon(h.payload(), pub)
    assert b["moon_id"] == "deadbeef01" and b["host"] == "192.168.1.20" and b["planet_port"] == h.server.port
    dest = tmp_path / "c"
    assert await fetch_planet("127.0.0.1", h.server.port, pub, b["planet_hash"], dest)
    assert dest.read_bytes() == b"MOON:192.168.1.20/9993"
    ip[0] = "10.0.0.7"                                   # DHCP renewed
    await asyncio.sleep(0.2)
    b2 = parse_beacon(h.payload(), pub)
    assert b2["host"] == "10.0.0.7" and b2["planet_hash"] != b["planet_hash"] and len(calls) == 2
    assert await fetch_planet("127.0.0.1", h.server.port, pub, b2["planet_hash"], dest)
    assert dest.read_bytes() == b"MOON:10.0.0.7/9993"
    await h.stop()


async def test_no_ip_refuses_to_open(tmp_path):
    priv, _ = S.generate_keypair()
    h = HostRoom(priv, tmp_path, tmp_path / "w", "n", lambda: None, "1.0", build=_build_factory([]))
    try:
        await h.start(); assert False
    except RuntimeError:
        pass
