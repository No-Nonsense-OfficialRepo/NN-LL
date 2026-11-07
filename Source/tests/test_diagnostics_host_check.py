import socket
import threading
import time

from lantool.diagnostics import host_check
from lantool.diagnostics.host_check import host_room_checks, local_ipv4s, udp_port_in_use
from lantool.diagnostics.runner import run_checks
from lantool.netcore.beacon import make_beacon
from lantool.trust.signing import generate_keypair


def _tcp_listener():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    s.listen(4)
    return s


def _udp_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("0.0.0.0", 0))
        return s.getsockname()[1]


def _own_checks(names=("hostPorts", "hostBeacon", "hostAdvertisedIp"), **kw):
    """Only the new checks (skip the PowerShell-based reused ones)."""
    return [c for c in host_room_checks(**kw) if c.name in names]


def _run(checks):
    return {r.name: r for r in run_checks(checks).results}


def test_local_ips_include_loopback():
    assert "127.0.0.1" in local_ipv4s()


def test_udp_port_in_use_detects_a_bound_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as owner:
        owner.bind(("0.0.0.0", 0))
        assert udp_port_in_use(owner.getsockname()[1]) is True
    assert udp_port_in_use(_udp_free_port()) is False


def test_ports_ok_when_everything_listens():
    a, b, c = _tcp_listener(), _tcp_listener(), _tcp_listener()
    udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp.bind(("0.0.0.0", 0))
    try:
        results = _run(_own_checks(presence_port=a.getsockname()[1], room_port=b.getsockname()[1],
                                   sync_port=c.getsockname()[1], query_port=udp.getsockname()[1],
                                   listen_s=0.2))
        assert results["hostPorts"].status == "ok"
    finally:
        for s in (a, b, c, udp):
            s.close()


def test_ports_names_what_is_not_listening():
    a = _tcp_listener()
    closed = _tcp_listener()
    closed_port = closed.getsockname()[1]
    closed.close()
    try:
        results = _run(_own_checks(presence_port=a.getsockname()[1], room_port=closed_port,
                                   sync_port=a.getsockname()[1], query_port=_udp_free_port(), listen_s=0.2))
        res = results["hostPorts"]
        assert res.status == "fail"
        assert "tcp room" in res.summary and "udp discovery" in res.summary and "tcp presence" not in res.summary
    finally:
        a.close()


def _send_beacons(port, payload, stop):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    while not stop.is_set():
        s.sendto(payload, ("127.0.0.1", port))
        time.sleep(0.05)
    s.close()


def _with_beacons(advertised_host, **extra):
    priv, pub = generate_keypair()
    port = _udp_free_port()
    payload = make_beacon(priv, "abcdef0123456789", advertised_host, 47800, "hash", "t", host_pub=pub,
                          pc_name="HOSTPC")
    stop = threading.Event()
    thread = threading.Thread(target=_send_beacons, args=(port, payload, stop), daemon=True)
    thread.start()
    try:
        return _run(_own_checks(names=("hostBeacon", "hostAdvertisedIp"), beacon_port=port, listen_s=2.0, **extra))
    finally:
        stop.set()
        thread.join(1)


def test_beacon_heard_and_advertised_address_is_this_pc():
    results = _with_beacons("127.0.0.1")
    assert results["hostBeacon"].status == "ok"
    assert results["hostBeacon"].data["pc_name"] == "HOSTPC"
    assert results["hostAdvertisedIp"].status == "ok"


def test_advertised_address_that_is_not_this_pc_fails():
    results = _with_beacons("203.0.113.77")
    assert results["hostAdvertisedIp"].status == "fail"
    assert "203.0.113.77" in results["hostAdvertisedIp"].summary


def test_extra_ips_count_as_this_pc():
    results = _with_beacons("203.0.113.77", extra_ips=["203.0.113.77"])
    assert results["hostAdvertisedIp"].status == "ok"


def test_no_beacon_is_a_warning_and_skips_the_address_check():
    results = _run(_own_checks(names=("hostBeacon", "hostAdvertisedIp"), beacon_port=_udp_free_port(), listen_s=0.3))
    assert results["hostBeacon"].status == "warn"
    assert "typing your IP" in results["hostBeacon"].summary
    assert results["hostAdvertisedIp"].status == "skipped"


def test_full_list_reuses_general_checks_without_duplicates():
    names = [c.name for c in host_room_checks()]
    assert names[:3] == ["hostPorts", "hostBeacon", "hostAdvertisedIp"]
    assert set(names[3:]) == {"timeStatus", "clockOffsetSamples", "vlaService", "vlaStatus", "firewall"}
    assert len(names) == len(set(names))
