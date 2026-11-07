"""RoomController failure details: planet fetch reason and ZeroTier address failure kinds."""
import asyncio

from lantool.netcore.controller import RoomController, State
from lantool.netcore.errors import Code, Stage


class FakeAdapter:
    def prefer_zerotier(self, alias):
        pass

    def restore(self):
        pass


class FakePresence:
    def repoint(self, host, port):
        pass


class FakeZT:
    def __init__(self, ip="10.147.1.2", failure="", error=""):
        self.ip, self.last_failure, self.last_error = ip, failure, error

    async def join(self, net_id):
        pass

    async def leave(self, net_id):
        pass

    async def wait_ip(self, net_id):
        return self.ip

    def alias(self, net_id):
        return "ZeroTier One"


class FakeMoon:
    def __init__(self, ok, last_error=""):
        self.ok, self.last_error = ok, last_error

    async def fetch_and_install(self, beacon):
        return self.ok


BEACON = {"net_id": "abc", "moon_id": "m1", "planet_hash": "new", "host": "10.0.0.2"}


def _controller(zt, moon):
    return RoomController(zt, FakeAdapter(), FakePresence(), lambda: "old",
                          moon.fetch_and_install, lambda b: "10.147.1.1", settle_s=0)


def _run(controller, beacon=BEACON):
    asyncio.run(controller.on_beacon(dict(beacon)))
    return controller


def test_planet_failure_uses_moon_sync_reason():
    c = _run(_controller(FakeZT(), FakeMoon(False, "Couldn't verify the signed file.")))
    assert c.state == State.ETHERNET
    assert c.join_error.stage == Stage.PLANET
    assert c.join_error.code == Code.PLANET_FETCH
    assert c.error == "Couldn't verify the signed file."


def test_planet_failure_without_reason_keeps_generic_message():
    c = _run(_controller(FakeZT(), FakeMoon(False, "")))
    assert c.join_error.stage == Stage.PLANET
    assert c.error == "couldn't join room"


def test_bad_room_is_room_key_stage():
    zt = FakeZT(ip=None, failure="bad_room", error="Room not found.")
    c = _run(_controller(zt, FakeMoon(True)))
    assert c.join_error.stage == Stage.ROOM_KEY
    assert c.join_error.code == Code.ROOM_MISMATCH
    assert c.join_error.hint


def test_address_timeout_has_timeout_code():
    zt = FakeZT(ip=None, failure="timeout", error="No address yet.")
    c = _run(_controller(zt, FakeMoon(True)))
    assert c.join_error.stage == Stage.ADDRESS
    assert c.join_error.code == Code.TIMEOUT


def test_address_error_keeps_no_address_code():
    zt = FakeZT(ip=None, failure="error", error="Network error.")
    c = _run(_controller(zt, FakeMoon(True)))
    assert c.join_error.stage == Stage.ADDRESS
    assert c.join_error.code == Code.NO_ADDRESS


def test_address_failure_without_kind_keeps_no_address_code():
    c = _run(_controller(FakeZT(ip=None), FakeMoon(True)))
    assert c.join_error.code == Code.NO_ADDRESS
    assert "did not assign" in c.error


def test_success_clears_errors():
    c = _run(_controller(FakeZT(), FakeMoon(True)))
    assert c.state == State.ZEROTIER
    assert c.error is None and c.join_error is None
