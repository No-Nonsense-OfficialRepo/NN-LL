import asyncio, hashlib
from pathlib import Path
from silent_tunnel import Tunnel, CONNECTED
from silent_tunnel.authorizer import AutoAuthorizer
from silent_tunnel.planet import install_planet, current_planet_hash
from lantool.netcore.zt_adapter import SilentTunnelZT
from lantool.netcore.controller import RoomController, State
from lantool.netcore.beacon import make_beacon, parse_beacon
from lantool.trust.signing import generate_keypair

NW = "8056c2e21c000001"


class FakeLocal:
    def __init__(self): self.nets = {}; self.members = []; self.authorized = []; self.left = []
    def status(self): return {"address": "aabbccddee"}
    def networks(self): return list(self.nets.values())
    def network(self, n): return self.nets.get(n)
    def join(self, n): self.nets[n] = {"id": n, "status": "OK", "portDeviceName": "ZeroTier One [x]",
                                       "assignedAddresses": ["10.147.20.5/24"]}
    def leave(self, n): self.left.append(n); self.nets.pop(n, None)
    def controller_members(self, n): return self.members
    def authorize_member(self, n, node, ip=None): self.authorized.append(node)


class FakeInstaller:
    def __init__(self, installed): self.installed, self.uninstalled = installed, 0
    def is_installed(self): return self.installed
    def install(self, d, say): self.installed = True
    def uninstall(self, say): self.uninstalled += 1; self.installed = False; return True


def mk(tmp_path, installed):
    inst = FakeInstaller(installed)
    return Tunnel(home=tmp_path, local=FakeLocal(), installer=inst, poll_interval=0.01), inst


def test_cleanup_keeps_users_own_zerotier(tmp_path):
    t, inst = mk(tmp_path, installed=True)          # user already had ZeroTier
    t.ensure_ready(); t.cleanup()
    assert inst.uninstalled == 0 and inst.installed and not t.state.installed_by_us


def test_cleanup_removes_zerotier_we_installed(tmp_path):
    t, inst = mk(tmp_path, installed=False)
    t.settings.uninstall_on_exit = True  # Explicit opt-in; default keeps fast startup.
    t.ensure_ready(); assert t.state.installed_by_us
    t.cleanup()
    assert inst.uninstalled == 1
    t2, inst2 = mk(tmp_path / "b", installed=False)
    t2.settings.uninstall_on_exit = False           # "keep installed" setting
    t2.ensure_ready(); t2.cleanup(); assert inst2.uninstalled == 0


def test_approval_policy_blocks_unknown_joiner():
    fl = FakeLocal(); fl.members = [{"nodeId": "1111111111", "config": {}}, {"nodeId": "2222222222", "config": {}}]
    a = AutoAuthorizer(fl, NW, "aabbccddee", "10.147.20.1", policy=lambda n: n == "1111111111")
    assert a.poll_once() == ["1111111111"] and fl.authorized == ["1111111111"] and a.denied == {"2222222222"}
    fl2 = FakeLocal(); fl2.members = fl.members
    assert len(AutoAuthorizer(fl2, NW, "aabbccddee", "10.147.20.1").poll_once()) == 2   # default: auto-approve


def test_planet_install_backs_up_and_hashes(tmp_path):
    (tmp_path / "planet").write_bytes(b"official")
    install_planet(b"custom", home=tmp_path, restart=False)
    assert (tmp_path / "planet").read_bytes() == b"custom" and (tmp_path / "planet.orig").read_bytes() == b"official"
    assert current_planet_hash(tmp_path) == hashlib.sha256(b"custom").hexdigest()
    install_planet(b"custom2", home=tmp_path, restart=False)
    assert (tmp_path / "planet.orig").read_bytes() == b"official"   # original kept once


def test_beacon_optional_fields_roundtrip():
    priv, pub = generate_keypair()
    b = parse_beacon(make_beacon(priv, NW, "192.168.1.5", 47800, "h", "1", host_zt="10.147.20.1", planet_port=47802), pub)
    assert b["host_zt"] == "10.147.20.1" and b["planet_port"] == 47802


class Adapter:
    def __init__(self): self.log = []
    def prefer_zerotier(self, a): self.log.append(("prefer", a))
    def restore(self): self.log.append("restore")


class Presence:
    def __init__(self): self.to = None
    def repoint(self, h, p=None): self.to = h


async def test_room_controller_end_to_end_with_silent_tunnel(tmp_path):
    t, _ = mk(tmp_path, installed=True)
    ad, pr = Adapter(), Presence()
    async def fetch(b): return True
    rc = RoomController(SilentTunnelZT(t), ad, pr, lambda: "h", fetch, lambda b: b["host_zt"], settle_s=0)
    await rc.on_beacon({"net_id": NW, "planet_hash": "h", "host_zt": "10.147.20.1", "presence_port": 47800})
    assert rc.state == State.ZEROTIER and pr.to == "10.147.20.1" and ad.log == [("prefer", "ZeroTier One [x]")]
    await rc.leave()
    assert rc.state == State.ETHERNET and ad.log[-1] == "restore" and NW in t.local.left
