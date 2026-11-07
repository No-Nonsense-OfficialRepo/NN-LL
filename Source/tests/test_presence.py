import asyncio, json, pytest
from lantool.presence.server import PresenceServer
from lantool.presence import client as client_mod
from lantool.presence.client import PresenceClient
from lantool.presence.state import PresenceState


@pytest.mark.parametrize('game', [[], {}, ['bad'], 4, None, '', 'x' * 65])
def test_malformed_game_event_cannot_poison_counts(game):
    state = PresenceState()
    state.hello('p', 'Player')
    assert not state.apply('p', {'type': 'launch', 'game': game})
    assert state.counts() == {'players': 1, 'games': {}}


@pytest.mark.asyncio
async def test_large_initial_roster_and_playing_reconnect():
    server = PresenceServer('127.0.0.1', 0)
    await server.start()
    avatar = 'data:image/jpeg;base64,' + 'A' * 15000
    clients = [PresenceClient(str(i), 'Player', '127.0.0.1', server.port, avatar=avatar)
               for i in range(6)]
    seen = []
    clients[0].on_players = seen.append
    async def until(predicate):
        async with asyncio.timeout(5):
            while not predicate():
                await asyncio.sleep(.01)
    try:
        for client in clients:
            client.start()
        await asyncio.wait_for(asyncio.gather(*(c.connected.wait() for c in clients)), 3)
        await clients[0].subscribe_players()
        await until(lambda: seen and len(seen[-1]) == 6)
        assert all(p['avatar'] == avatar for p in seen[-1])
        await clients[0].launch('sample')
        await until(lambda: server.state.players['0'].state == 'playing')
        old = server.writers['0']
        clients[0].repoint('127.0.0.1')
        await until(lambda: server.writers.get('0') is not old and
                    server.state.players.get('0') and server.state.players['0'].state == 'playing')
        assert server.state.players['0'].game == 'sample'
    finally:
        for client in clients:
            await client.stop()
        await server.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize('version', ['0.9.24', None])
async def test_host_rejects_old_or_missing_release_before_registering_player(version):
    from lantool._version import __proto__
    server = PresenceServer('127.0.0.1', 0)
    await server.start()
    reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
    try:
        writer.write((json.dumps({'type': 'hello', 'player_id': 'stale', 'name': 'Old client',
                                 'launcher_version': version, 'proto': __proto__})+'\n').encode())
        await writer.drain()
        response = json.loads(await asyncio.wait_for(reader.readline(), 2))
        assert response['code'] == 'version_mismatch'
        assert 'stale' not in server.writers
        assert await asyncio.wait_for(reader.read(), 2) == b''
    finally:
        writer.close()
        await writer.wait_closed()
        await server.stop()


def test_state_counts_and_expiry():
    t = [0.0]
    s = PresenceState(clock=lambda: t[0])
    s.hello("a", "A"); s.hello("b", "B")
    s.apply("a", {"type": "hover", "game": "g"})
    s.apply("b", {"type": "launch", "game": "g"})
    assert s.counts()["games"]["g"] == {"hovering": 1, "playing": 1}
    t[0] = 16
    assert set(s.expire()) == {"a", "b"}
    assert s.counts()["players"] == 0


def test_avatar_relayed_only_when_small_inline_image():
    s = PresenceState()
    small = "data:image/jpeg;base64,AAAA"
    assert s.hello("a", "A", avatar=small).avatar == small
    assert s.hello("b", "B", avatar="file:///C:/x.png").avatar == ""
    assert s.hello("c", "C", avatar="data:image/jpeg;base64," + "A" * 16000).avatar == ""
    assert s.hello("d", "D").avatar == ""
    s.apply("d", {"type": "profile", "name": "D2", "avatar": small})
    assert s.players["d"].avatar == small and s.players["d"].name == "D2"
    s.apply("d", {"type": "profile", "name": "D2", "avatar": 123})
    assert s.players["d"].avatar == ""


def test_hover_does_not_override_playing():
    s = PresenceState(); s.hello("a", "A")
    s.apply("a", {"type": "launch", "game": "g"})
    s.apply("a", {"type": "hover", "game": "h"})
    assert s.players["a"].state == "playing" and s.players["a"].game == "g"


@pytest.mark.asyncio
async def test_ten_clients_hover_within_1s():
    """F5 acceptance: 10 clients hover one game, all see 10 within 1 s of the hover event."""
    client_mod.DWELL_S = 0.05  # speed up dwell for the test; dwell logic tested separately
    srv = PresenceServer(host="127.0.0.1", port=0)
    await srv.start()
    clients = [PresenceClient(f"p{i}", f"P{i}", "127.0.0.1", srv.port) for i in range(10)]
    for c in clients:
        c.start()
    await asyncio.wait_for(asyncio.gather(*(c.connected.wait() for c in clients)), 3)
    t0 = asyncio.get_running_loop().time()
    for c in clients:
        c.hover_start("bfbc2")
    while not all(c.counts["games"].get("bfbc2", {}).get("hovering") == 10 for c in clients):
        await asyncio.sleep(0.01)
        assert asyncio.get_running_loop().time() - t0 < 1.0 + client_mod.DWELL_S
    assert srv.state.counts()["games"]["bfbc2"]["hovering"] == 10
    for c in clients:
        await c.stop()
    await srv.stop()


@pytest.mark.asyncio
async def test_host_kick_removes_one_player_without_reconnecting():
    srv = PresenceServer(host='127.0.0.1', port=0)
    await srv.start()
    kicked = asyncio.Event()
    a = PresenceClient('a', 'A', '127.0.0.1', srv.port, on_kicked=kicked.set)
    b = PresenceClient('b', 'B', '127.0.0.1', srv.port)
    a.start(); b.start()
    try:
        await asyncio.wait_for(asyncio.gather(a.connected.wait(), b.connected.wait()), 3)
        assert await srv.kick('a')
        await asyncio.wait_for(kicked.wait(), 3)
        await asyncio.sleep(1.2)
        assert 'a' not in srv.writers
        assert 'b' in srv.writers
        assert not a.connected.is_set()
    finally:
        await a.stop(); await b.stop(); await srv.stop()


@pytest.mark.asyncio
async def test_admitted_room_members_can_publish_peer_seeds():
    """Protected room membership is checked at hello and seed updates are then accepted."""
    from lantool._version import __version__, __proto__

    class Admission:
        def listener_options(self):
            return {}

        def permits(self, token, player_id, *, ip=None):
            return token == "room-token" and player_id == "member"

    srv = PresenceServer("127.0.0.1", 0, admission=Admission())
    await srv.start()
    reader, writer = await asyncio.open_connection("127.0.0.1", srv.port)
    try:
        writer.write((json.dumps({"type": "hello", "player_id": "member", "name": "Member",
                                  "admission_token": "room-token", "launcher_version": __version__,
                                  "proto": __proto__}) + "\n").encode())
        await writer.drain()
        await asyncio.wait_for(reader.readline(), 2)  # initial ping
        await asyncio.wait_for(reader.readline(), 2)  # welcome
        writer.write(b'{"type":"seed_update","port":47805,"games":["game"]}\n')
        await writer.drain()
        for _ in range(20):
            if "member" in srv.seeders:
                break
            await asyncio.sleep(0.01)
        assert srv.seeders["member"]["games"] == ["game"]
    finally:
        writer.close()
        await writer.wait_closed()
        await srv.stop()


@pytest.mark.asyncio
async def test_dwell_cancelled_on_quick_leave():
    srv = PresenceServer(host="127.0.0.1", port=0); await srv.start()
    c = PresenceClient("x", "X", "127.0.0.1", srv.port); c.start()
    await asyncio.wait_for(c.connected.wait(), 3)
    client_mod.DWELL_S = 0.3
    c.hover_start("g"); await asyncio.sleep(0.1); c.hover_end_local(); await asyncio.sleep(0.5)
    assert srv.state.counts()["games"] == {}
    await c.stop(); await srv.stop()


def _roster(*pairs):
    return [{"player_id": pid, "name": pid, "state": "browsing", "game": None, "avatar": av} for pid, av in pairs]


@pytest.mark.asyncio
async def test_roster_sends_each_avatar_once_per_subscriber():
    srv = PresenceServer(host="127.0.0.1", port=0)
    small = "data:image/jpeg;base64,AAAA"
    players = _roster(("a", small), ("b", ""))
    hashes = {p["player_id"]: srv._avatar_hash(p["avatar"]) for p in players}
    first = json.loads(srv._roster_for("sub", players, hashes, {}))["players"]
    assert first[0]["avatar"] == small and first[0]["avatar_hash"] == hashes["a"]
    assert "avatar" not in first[1] and first[1]["avatar_hash"] == ""
    second = json.loads(srv._roster_for("sub", players, hashes, {}))["players"]
    assert "avatar" not in second[0] and second[0]["avatar_hash"] == hashes["a"]
    other = json.loads(srv._roster_for("sub2", players, hashes, {}))["players"]
    assert other[0]["avatar"] == small  # a second subscriber still needs it
    players[0]["avatar"] = small + "B"
    hashes["a"] = srv._avatar_hash(players[0]["avatar"])
    changed = json.loads(srv._roster_for("sub", players, hashes, {}))["players"]
    assert changed[0]["avatar"] == small + "B"  # a changed avatar is sent again
    shared = {}
    one = srv._roster_for("sub3", players, hashes, shared)
    assert srv._roster_for("sub4", players, hashes, shared) is one  # same need -> encoded once


@pytest.mark.asyncio
async def test_client_fills_avatars_from_cache_and_blanks_unknown_hash():
    c = PresenceClient("me", "Me", "127.0.0.1")
    full = [{"player_id": "a", "avatar_hash": "h1", "avatar": "data:image/jpeg;base64,AAAA"},
            {"player_id": "b", "avatar_hash": ""}]
    out = c._with_avatars(full)
    assert out[0]["avatar"] == "data:image/jpeg;base64,AAAA" and out[1]["avatar"] == ""
    assert all("avatar_hash" not in p for p in out)
    slim = [{"player_id": "a", "avatar_hash": "h1"}, {"player_id": "b", "avatar_hash": ""}]
    assert c._with_avatars(slim)[0]["avatar"] == "data:image/jpeg;base64,AAAA"
    assert c._with_avatars([{"player_id": "a", "avatar_hash": "h2"}])[0]["avatar"] == ""  # hash we never got
    assert c._with_avatars([{"player_id": "z", "avatar_hash": "h1"}])[0]["avatar"] == ""
    assert "a" not in c._avatar_cache  # players that left are dropped from the cache


@pytest.mark.asyncio
async def test_avatar_from_hello_reaches_subscribers_and_survives_later_rosters():
    client_mod.DWELL_S = 0.05
    srv = PresenceServer(host="127.0.0.1", port=0)
    await srv.start()
    small = "data:image/jpeg;base64,AAAA"
    seen = []
    a = PresenceClient("a", "A", "127.0.0.1", srv.port, avatar=small)  # avatar only in hello, no push_profile
    b = PresenceClient("b", "B", "127.0.0.1", srv.port, on_players=seen.append)
    a.start(); b.start()
    await asyncio.wait_for(asyncio.gather(a.connected.wait(), b.connected.wait()), 3)
    await b.subscribe_players()

    def avatar_of_a(roster):
        return next((p["avatar"] for p in roster if p["player_id"] == "a"), None)

    async def until(pred):
        for _ in range(300):
            if pred():
                return
            await asyncio.sleep(0.01)
        raise AssertionError("timed out waiting for roster")

    await until(lambda: seen and avatar_of_a(seen[-1]) == small)
    count = len(seen)
    a.hover_start("g")  # forces another roster broadcast, which carries only the hash
    await until(lambda: len(seen) > count)
    assert avatar_of_a(seen[-1]) == small
    assert all("avatar_hash" not in p for p in seen[-1])
    await a.stop(); await b.stop(); await srv.stop()
