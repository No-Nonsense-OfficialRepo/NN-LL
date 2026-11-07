"""Shape of the state.transfers payload the Downloads page receives (LauncherBridge._transfers)."""
from types import SimpleNamespace

from lantool.filesync.activity import ActivityTracker
from lantool.qt.bridge import LauncherBridge
from lantool.transfer_activity import build_transfers

LIB = {"wc3": {"name": "Warcraft III"}, "ra2": {"name": "Red Alert 2"}}
ROSTER = [{"player_id": "p1", "name": "Anna", "ip": "10.0.0.2"},
          {"player_id": "p2", "name": "Ben", "ip": "10.0.0.3"}]
PEERS = [{"player_id": "p1", "host": "10.0.0.2", "port": 47805, "games": ["wc3"]},
         {"player_id": "p2", "host": "10.0.0.3", "port": 47805, "games": ["wc3", "ra2"]}]
ROW_KEYS = {"id", "name", "downloading", "seeding", "from", "to"}
ITEM_KEYS = {"name", "kind", "active", "bytes"}


def _bridge_like(progress_game_id="", active=True, uploads=None):
    uploads_tracker = ActivityTracker()
    for who, game, n in (uploads or []):
        uploads_tracker.record(who, game, n)
    received = ActivityTracker()
    received.record("10.0.0.2:47805", "wc3", 10)
    return SimpleNamespace(
        _progress={"active": active, "game_id": progress_game_id, "done": 0, "total": 0, "file": "", "state": "receiving"},
        library=LIB, seeded_games={"ra2"}, peer_sources=PEERS, _roster=ROSTER,
        received_activity=received,
        _cancel_delete=None,
        peer_file_server=None,
        file_sync_server=SimpleNamespace(activity=uploads_tracker),
        last_beacon={"host_zt": "10.0.0.9"},
        config_data={"player_id": "me"},
    )


def test_build_transfers_row_and_item_shape():
    rows = build_transfers(
        library=LIB, downloading="wc3", seeded={"ra2"}, peer_sources=PEERS, roster=ROSTER,
        received=[{"who": "10.0.0.2:47805", "game": "wc3", "bytes": 10, "active": True}],
        uploads=[{"who": "10.0.0.3", "game": "ra2", "bytes": 5, "active": False}],
        host_ip="10.0.0.9", my_id="me")
    assert [r["id"] for r in rows] == ["wc3", "ra2"]          # downloading game sorts first
    for row in rows:
        assert set(row) == ROW_KEYS
        assert isinstance(row["downloading"], bool) and isinstance(row["seeding"], bool)
        for item in row["from"] + row["to"]:
            assert set(item) == ITEM_KEYS
            assert item["kind"] in ("host", "peer") and isinstance(item["bytes"], int)
            assert isinstance(item["active"], bool)
    assert rows[0]["name"] == "Warcraft III" and rows[0]["downloading"] is True
    assert rows[1]["downloading"] is False and rows[1]["seeding"] is True
    assert [t["name"] for t in rows[1]["to"]] == ["Ben"]


def test_bridge_transfers_payload_while_downloading():
    payload = LauncherBridge._transfers(_bridge_like(progress_game_id="wc3",
                                                     uploads=[("10.0.0.3", "ra2", 5)]))
    assert [r["id"] for r in payload] == ["wc3", "ra2"]
    wc3 = payload[0]
    assert set(wc3) == ROW_KEYS and wc3["downloading"] is True
    sources = {s["name"]: s for s in wc3["from"]}
    assert set(sources) == {"Host", "Anna", "Ben"}
    assert sources["Anna"]["active"] is True and sources["Anna"]["bytes"] == 10
    assert sources["Host"]["kind"] == "host"
    assert payload[1]["seeding"] is True and [t["name"] for t in payload[1]["to"]] == ["Ben"]


def test_host_player_list_shows_seeding_up_and_leeching_down_per_player():
    ns = _bridge_like(uploads=[("10.0.0.3", "ra2", 5)])
    ns._roster = ROSTER + [{"player_id": "p4", "name": "Dan", "ip": "10.0.0.5"}]
    players = {p["name"]: p for p in LauncherBridge._players_with_activity(ns)}
    assert players["Anna"]["seedingActive"] is True
    assert [g["id"] for g in players["Anna"]["seeding"]] == ["wc3"] and players["Anna"]["leeching"] == []
    assert players["Anna"]["leechingActive"] is False
    ben = players["Ben"]
    assert sorted(g["id"] for g in ben["seeding"]) == ["ra2", "wc3"]
    assert [(g["id"], g["active"]) for g in ben["leeching"]] == [("ra2", True)] and ben["leechingActive"] is True
    dan = players["Dan"]
    assert dan["seeding"] == [] and dan["seedingActive"] is False and dan["leechingActive"] is False
    assert players["Ben"]["player_id"] == "p2"                     # roster fields kept


def test_bridge_transfers_payload_when_idle_has_no_download_rows():
    payload = LauncherBridge._transfers(_bridge_like(active=False))
    assert all(r["downloading"] is False for r in payload)
    assert [r["id"] for r in payload] == ["ra2", "wc3"]        # both idle: sorted by name
    wc3 = next(r for r in payload if r["id"] == "wc3")
    assert [(s["name"], s["active"]) for s in wc3["from"]] == [("Anna", True), ("Ben", False)]
    assert all(s["kind"] == "peer" for s in wc3["from"])       # no Host row when not downloading
