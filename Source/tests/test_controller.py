import pytest
from lantool.netcore.controller import RoomController, State


class FakeZT:
    def __init__(self, ip="10.147.17.5"): self.ip, self.joined = ip, []
    async def join(self, n): self.joined.append(n)
    async def leave(self, n): self.joined.remove(n)
    async def wait_ip(self, n): return self.ip
    def alias(self, n): return "ZeroTier One [x]"

class FakeAdapter:
    def __init__(self): self.calls = []
    def prefer_zerotier(self, a): self.calls.append(("prefer", a))
    def restore(self): self.calls.append(("restore",))

class FakePresence:
    def __init__(self): self.pointed = None
    def repoint(self, h, p=None): self.pointed = (h, p)

B = {"net_id": "n1", "host": "192.168.1.2", "presence_port": 47800, "planet_hash": "h1", "moon_id": "test-moon"}

def mk(zt=None, fetch=None, local="h1"):
    zt = zt or FakeZT(); ad, pr = FakeAdapter(), FakePresence()
    async def ok(b): return True
    c = RoomController(zt, ad, pr, lambda: local, fetch or ok, lambda b: "10.147.17.1", settle_s=0)
    return c, zt, ad, pr

async def test_switch_to_zerotier_and_back():
    c, zt, ad, pr = mk()
    await c.on_beacon(B)
    assert c.state == State.ZEROTIER and pr.pointed == ("10.147.17.1", 47800) and zt.joined == ["n1"]
    assert ad.calls[0][0] == "prefer" and not c.launch_blocked
    await c.leave()
    assert c.state == State.ETHERNET and ad.calls[-1] == ("restore",) and zt.joined == []

async def test_stale_planet_reserved_once():
    called = []
    async def fetch(b): called.append(1); return True
    c, *_ = mk(fetch=fetch, local="old")
    await c.on_beacon(B); assert called == [1] and c.state == State.ZEROTIER

async def test_tampered_planet_stays_on_ethernet():
    async def bad(b): return False
    c, zt, ad, pr = mk(fetch=bad, local="old")
    await c.on_beacon(B)
    assert c.state == State.ETHERNET and c.error == "couldn't join room" and zt.joined == [] and pr.pointed is None

async def test_no_ip_falls_back():
    c, *_ = mk(zt=FakeZT(ip=None)); await c.on_beacon(B)
    assert c.state == State.ETHERNET and c.error
