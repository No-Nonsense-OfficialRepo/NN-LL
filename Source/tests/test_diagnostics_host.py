"""Host 'Check my room' against a real loopback FakeHost (reuses the ladder fixture)."""
import pytest

from lantool.diagnostics import host_checks as hc
from lantool.diagnostics.model import CheckResult
from lantool.diagnostics.runner import run_checks

from tests.test_diagnostics_ladder import FakeHost, HOST, _closed_port  # noqa: F401
from tests.test_diagnostics_ladder import host  # noqa: F401  (fixture)


@pytest.fixture(autouse=True)
def _no_system_calls(monkeypatch):
    monkeypatch.setattr(hc, "clock_offset", lambda report=None: CheckResult("", "ok", {}, "clock ok"))
    monkeypatch.setattr(hc, "firewall", lambda report=None: CheckResult("", "ok", {}, "firewall ok"))


def run(h, ips=(HOST,), room_port=None, tcp_timeout=1.5):
    checks = hc.host_checks(room_port=room_port or h.room_port, ips_fn=lambda: set(ips),
                            query_port=h.udp_port, udp_timeout=0.6, tcp_timeout=tcp_timeout)
    return {r.name: r for r in run_checks(checks).results}


def test_healthy_room_is_all_ok(host):
    res = run(host())
    assert {n: r.status for n, r in res.items()} == {
        "hostTcpRoom": "ok", "hostRoomResponse": "ok", "hostPorts": "ok",
        "hostUdpDiscovery": "ok", "hostAdvertisedAddress": "ok",
        "hostClockOffset": "ok", "hostFirewall": "ok"}


def test_closed_room_skips_dependents_but_not_discovery(host):
    res = run(host(), room_port=_closed_port(), tcp_timeout=4)
    assert res["hostTcpRoom"].status == "fail"
    assert res["hostRoomResponse"].status == "skipped"
    assert res["hostAdvertisedAddress"].status == "skipped"
    assert res["hostUdpDiscovery"].status == "ok"


def test_advertised_address_not_on_this_pc_warns(host):
    res = run(host(), ips=("192.168.1.50",))
    assert res["hostAdvertisedAddress"].status == "warn"
    assert "not on any adapter" in res["hostAdvertisedAddress"].summary
    assert res["hostAdvertisedAddress"].data["local"] == ["192.168.1.50"]


def test_blocked_presence_port_fails(host):
    res = run(host(presence=False), tcp_timeout=4)
    assert res["hostPorts"].status == "fail"


def test_tampered_reply_skips_advertised_address(host):
    res = run(host(tamper=True))
    assert res["hostRoomResponse"].status == "fail"
    assert res["hostAdvertisedAddress"].status == "skipped"


def test_link_local_advertised_address_fails(host, monkeypatch):
    h = host()
    orig = h.beacon
    from lantool.netcore.beacon import make_beacon
    import time
    monkeypatch.setattr(h, "beacon", lambda now=None: make_beacon(
        h.priv, "abcdef0123456789", "169.254.10.20", h.presence_port, "hash", h.version,
        now=now or time.time(), host_pub=h.pub, sync_port=h.sync_port, pc_name="HOSTPC"))
    res = run(h, ips=("169.254.10.20",))
    assert res["hostAdvertisedAddress"].status == "fail"
    assert "link-local" in res["hostAdvertisedAddress"].summary


def test_local_ipv4s_returns_set_without_wildcard():
    ips = hc.local_ipv4s()
    assert isinstance(ips, set) and "0.0.0.0" not in ips
