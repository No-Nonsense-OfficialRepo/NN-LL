"""Client ladder against a real loopback 'Host' (signed /room, TCP ports, UDP discovery)."""
import json
import socket
import threading
import time

import pytest

from lantool._version import __version__
from lantool.diagnostics.ladder import client_ladder_checks, tcp_probe
from lantool.diagnostics.runner import run_checks
from lantool.netcore.beacon import make_beacon
from lantool.trust.signing import generate_keypair

HOST = "127.0.0.1"


def _closed_port():
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


class FakeHost:
    """Serves /room over TCP, plain listener ports and a UDP discovery responder."""

    def __init__(self, *, ts_offset=0, version=__version__, tamper=False, malformed=False,
                 not_http=False, presence=True, sync=True, udp=True, proto=None):
        self.priv, self.pub = generate_keypair()
        self.ts_offset, self.version, self.proto = ts_offset, version, proto
        self.tamper, self.malformed, self.not_http = tamper, malformed, not_http
        self._socks, self._stop = [], threading.Event()
        self.presence_port = self._listener() if presence else _closed_port()
        self.sync_port = self._listener() if sync else _closed_port()
        self.room_port = self._room_server()
        self.udp_port = self._udp() if udp else _closed_port()

    def beacon(self, now=None):
        return make_beacon(self.priv, "abcdef0123456789", HOST, self.presence_port, "hash",
                           self.version, now=now or time.time() + self.ts_offset,
                           host_pub=self.pub, sync_port=self.sync_port, pc_name="HOSTPC",
                           proto=self.proto)

    def _listener(self):
        s = socket.socket()
        s.bind((HOST, 0))
        s.listen(8)
        self._socks.append(s)
        threading.Thread(target=self._accept_close, args=(s,), daemon=True).start()
        return s.getsockname()[1]

    def _accept_close(self, s):
        while not self._stop.is_set():
            try:
                conn, _ = s.accept()
                conn.close()
            except OSError:
                return

    def _room_server(self):
        s = socket.socket()
        s.bind((HOST, 0))
        s.listen(8)
        self._socks.append(s)

        def serve():
            while not self._stop.is_set():
                try:
                    conn, _ = s.accept()
                except OSError:
                    return
                with conn:
                    conn.settimeout(2)
                    try:
                        conn.recv(1024)
                    except OSError:
                        continue
                    body = self.beacon()
                    if self.tamper:
                        body = body.replace(b"HOSTPC", b"EVILPC")
                    if self.malformed:
                        body = b"not json at all"
                    head = b"HTTP/1.0 404 Not Found\r\n\r\n" if self.not_http else b"HTTP/1.0 200 OK\r\n\r\n"
                    conn.sendall(head + body)
        threading.Thread(target=serve, daemon=True).start()
        return s.getsockname()[1]

    def _udp(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind((HOST, 0))
        s.settimeout(0.2)
        self._socks.append(s)

        def serve():
            while not self._stop.is_set():
                try:
                    data, addr = s.recvfrom(1024)
                except socket.timeout:
                    continue
                except OSError:
                    return
                s.sendto(self.beacon(), addr)
        threading.Thread(target=serve, daemon=True).start()
        return s.getsockname()[1]

    def close(self):
        self._stop.set()
        for s in self._socks:
            s.close()


@pytest.fixture
def host():
    made = []

    def make(**kw):
        h = FakeHost(**kw)
        made.append(h)
        return h
    yield make
    for h in made:
        h.close()


def ladder(h, address=HOST, room_port=None, tcp_timeout=1.5, trusted_pub=None):
    # Windows takes ~2s to report a refused loopback connection, so tests that
    # expect 'refused' (not 'timeout') pass a longer tcp_timeout.
    checks = client_ladder_checks(address, room_port=room_port or h.room_port,
                                  query_port=h.udp_port, udp_timeout=0.6, tcp_timeout=tcp_timeout,
                                  trusted_pub=trusted_pub)
    return {r.name: r for r in run_checks(checks).results}


def test_everything_reachable_is_all_ok(host):
    results = ladder(host())
    assert {n: r.status for n, r in results.items()} == {
        "ladderTcpRoom": "ok", "ladderRoomResponse": "ok", "ladderIdentity": "ok", "ladderClock": "ok",
        "ladderPorts": "ok", "ladderVersion": "ok", "ladderUdpDiscovery": "ok"}
    assert results["ladderRoomResponse"].data["beacon"]["pc_name"] == "HOSTPC"


def test_reports_never_contain_signature_or_key(host):
    results = ladder(host())
    text = json.dumps(results["ladderRoomResponse"].data)
    assert "sig" not in text and "host_pub" not in text


def test_matching_pinned_key_passes(host):
    h = host()
    r = ladder(h, trusted_pub=h.pub)["ladderIdentity"]
    assert r.status == "ok" and r.data == {"pinned": True, "match": True}


def test_wrong_pinned_key_fails_identity(host):
    h = host()
    _, other_pub = generate_keypair()
    r = ladder(h, trusted_pub=other_pub)["ladderIdentity"]
    assert r.status == "fail" and "does not match" in r.summary
    assert other_pub not in json.dumps(r.data) and h.pub not in json.dumps(r.data)


def test_identity_skipped_when_room_reply_failed(host):
    results = ladder(host(tamper=True), trusted_pub="x")
    assert results["ladderIdentity"].status == "skipped"


def test_closed_room_port_stops_at_the_first_rung(host):
    h = host()
    results = ladder(h, room_port=_closed_port(), tcp_timeout=4)
    assert results["ladderTcpRoom"].status == "fail"
    assert "no room is open" in results["ladderTcpRoom"].summary
    for name in ("ladderRoomResponse", "ladderIdentity", "ladderClock", "ladderPorts", "ladderVersion"):
        assert results[name].status == "skipped"
    assert results["ladderUdpDiscovery"].status == "ok"   # independent rung still runs


def test_unreachable_address_is_reported_as_no_route():
    assert tcp_probe("203.0.113.1", 47802, timeout=0.3)[0] in ("timeout", "unreachable")


def test_tampered_reply_fails_signature_and_skips_the_rest(host):
    results = ladder(host(tamper=True))
    assert results["ladderRoomResponse"].status == "fail"
    assert "signature" in results["ladderRoomResponse"].summary
    assert results["ladderClock"].status == results["ladderPorts"].status == "skipped"


def test_malformed_reply_fails(host):
    results = ladder(host(malformed=True))
    assert results["ladderRoomResponse"].status == "fail"
    assert "malformed" in results["ladderRoomResponse"].summary


def test_non_room_http_answer_fails(host):
    results = ladder(host(not_http=True))
    assert results["ladderRoomResponse"].status == "fail"
    assert "not with a room" in results["ladderRoomResponse"].summary


@pytest.mark.parametrize("offset, status, word", [(-120, "fail", "ahead"), (120, "fail", "behind"),
                                                  (-20, "warn", "ahead"), (-3, "ok", "agree")])
def test_clock_skew_levels(host, offset, status, word):
    results = ladder(host(ts_offset=offset))
    assert results["ladderRoomResponse"].status == "ok"   # signature valid even when stale
    assert results["ladderClock"].status == status
    assert word in results["ladderClock"].summary


def test_stale_clock_also_degrades_udp_discovery(host):
    results = ladder(host(ts_offset=-120))
    assert results["ladderUdpDiscovery"].status == "warn"
    assert "clocks" in results["ladderUdpDiscovery"].summary


def test_blocked_presence_port_is_a_failure(host):
    results = ladder(host(presence=False), tcp_timeout=4)
    assert results["ladderPorts"].status == "fail"
    assert results["ladderPorts"].data["presence"]["state"] == "refused"


def test_blocked_sync_port_is_only_a_warning(host):
    results = ladder(host(sync=False))
    assert results["ladderPorts"].status == "warn"
    assert "downloads" in results["ladderPorts"].summary


def test_version_mismatch_fails(host):
    results = ladder(host(version="0.0.1-other"))
    assert results["ladderVersion"].status == "fail"
    assert "0.0.1-other" in results["ladderVersion"].summary


def test_protocol_mismatch_fails_version_check(host):
    results = ladder(host(proto=99))
    assert results["ladderVersion"].status == "fail"
    assert "different connection protocols" in results["ladderVersion"].summary


def test_no_udp_reply_warns_but_typed_ip_still_works(host):
    results = ladder(host(udp=False))
    assert results["ladderUdpDiscovery"].status == "warn"
    assert "typing its IP still works" in results["ladderUdpDiscovery"].summary
    assert results["ladderRoomResponse"].status == "ok"
