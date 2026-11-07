import asyncio

from lantool.filesync.activity import ACTIVE_SECONDS, FORGET_SECONDS, ActivityTracker
from lantool.filesync.peer import PeerFileServer
from lantool.transfer_activity import build_transfers


class Clock:
    now = 100.0

    def __call__(self):
        return self.now


def test_tracker_active_then_idle_then_forgotten():
    clock = Clock()
    t = ActivityTracker(clock)
    t.record("10.0.0.2", "wc3", 500)
    t.record("10.0.0.2", "wc3", 500)
    t.record("10.0.0.3", "", 5)       # no game: ignored
    t.record("10.0.0.3", "wc3", 0)    # no bytes: ignored
    assert t.snapshot() == [{"who": "10.0.0.2", "game": "wc3", "bytes": 1000, "active": True}]
    clock.now += ACTIVE_SECONDS + 1
    assert t.snapshot("wc3")[0]["active"] is False
    assert t.snapshot("other") == []
    clock.now += FORGET_SECONDS
    assert t.snapshot() == []


LIB = {"wc3": {"name": "Warcraft III"}, "ra2": {"name": "Red Alert 2"}}
ROSTER = [{"player_id": "p1", "name": "Anna", "ip": "10.0.0.2"},
          {"player_id": "p2", "name": "Ben", "ip": "10.0.0.3"},
          {"player_id": "p3", "name": "Cara", "ip": "10.0.0.4"}]
PEERS = [{"player_id": "p1", "host": "10.0.0.2", "port": 47805, "games": ["wc3"]},
         {"player_id": "p2", "host": "10.0.0.3", "port": 47805, "games": ["wc3", "ra2"]},
         {"player_id": "p3", "host": "10.0.0.4", "port": 47805, "games": ["ra2"]}]


def test_download_lists_host_and_every_seeder_by_name():
    rows = build_transfers(
        library=LIB, downloading="wc3", seeded=set(), peer_sources=PEERS, roster=ROSTER,
        received=[{"who": "10.0.0.9:47803", "game": "wc3", "bytes": 4_000_000, "active": True},
                  {"who": "10.0.0.3:47805", "game": "wc3", "bytes": 2_000_000, "active": True}],
        uploads=[], host_ip="10.0.0.9", my_id="me")
    assert [r["id"] for r in rows] == ["wc3"]
    sources = {s["name"]: s for s in rows[0]["from"]}
    assert set(sources) == {"Host", "Anna", "Ben"}          # Cara does not have wc3
    assert sources["Host"]["bytes"] == 4_000_000 and sources["Ben"]["active"]
    assert sources["Anna"]["bytes"] == 0 and not sources["Anna"]["active"]
    assert rows[0]["downloading"] and not rows[0]["to"]


def test_seeding_game_lists_who_downloads_from_me():
    rows = build_transfers(
        library=LIB, downloading="", seeded={"ra2"}, peer_sources=[], roster=ROSTER, received=[],
        uploads=[{"who": "10.0.0.2", "game": "ra2", "bytes": 3_000_000, "active": True},
                 {"who": "10.0.0.77", "game": "ra2", "bytes": 10, "active": False}], host_ip="")
    assert [r["id"] for r in rows] == ["ra2"] and rows[0]["seeding"] and not rows[0]["downloading"]
    assert [(t["name"], t["active"]) for t in rows[0]["to"]] == [("Anna", True), ("Unknown (10.0.0.77)", False)]


def test_idle_games_are_left_out_and_own_player_is_not_a_source():
    peers = PEERS + [{"player_id": "me", "host": "10.0.0.50", "port": 1, "games": ["wc3"]}]
    rows = build_transfers(library=LIB, downloading="wc3", seeded=set(), peer_sources=peers, roster=ROSTER,
                           received=[], uploads=[], host_ip="10.0.0.9", my_id="me")
    assert [r["id"] for r in rows] == ["wc3"]
    assert all(s["name"] != "10.0.0.50" for s in rows[0]["from"])


async def test_sync_records_received_from_host_and_host_records_sent(tmp_path):
    from lantool.filesync.client import sync_game
    from lantool.filesync.server import FileSyncServer
    from lantool.trust.signing import generate_keypair
    priv, pub = generate_keypair()
    game = tmp_path / "host" / "game"
    game.mkdir(parents=True)
    (game / "game.exe").write_bytes(b"y" * 300_000)
    server = FileSyncServer(priv, tmp_path / "host", host="127.0.0.1", port=0)
    await server.start()
    received = ActivityTracker()
    try:
        res = await sync_game("127.0.0.1", server.port, pub, "game", tmp_path / "client", received=received)
        assert res.ok, res.error
    finally:
        await server.stop()
    rows = received.snapshot("game")
    assert [r["who"] for r in rows] == [f"127.0.0.1:{server.port}"] and rows[0]["bytes"] == 300_000
    assert [(r["who"], r["bytes"]) for r in server.activity.snapshot("game")] == [("127.0.0.1", 300_000)]


async def test_peer_server_records_who_it_sent_to(tmp_path):
    game = tmp_path / "wc3"
    game.mkdir()
    (game / "a.bin").write_bytes(b"x" * 4096)
    server = PeerFileServer(tmp_path, host="127.0.0.1", port=0)
    server.set_shared_files({"wc3": ["a.bin"]})
    await server.start()
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", server.port)
        writer.write(b"GET /piece/wc3/a.bin HTTP/1.0\r\nRange: bytes=0-4095\r\n\r\n")
        await writer.drain()
        data = await reader.read()
        writer.close()
        assert data.endswith(b"x" * 4096)
        rows = server.activity.snapshot("wc3")
        assert rows == [{"who": "127.0.0.1", "game": "wc3", "bytes": 4096, "active": True}]
    finally:
        await server.stop()
