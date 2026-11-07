"""Host-side 'Check my room': is this PC really serving what clients will look for?

Read-only and local: it connects to this PC's own ports, binds a UDP socket briefly
to see the room announcements, and compares the advertised address with the NICs.
Firewall, clock, VLA and listener checks are reused from the general checks.
"""
from __future__ import annotations
import socket
import time
from concurrent.futures import ThreadPoolExecutor

from ..netcore.beacon import BEACON_PORT, parse_beacon
from ..netcore.discovery import QUERY_PORT
from .checks import default_checks
from .ladder import PRESENCE_PORT, ROOM_PORT, SYNC_PORT, tcp_probe
from .model import Check, CheckResult, Report, OK, WARN, FAIL, SKIPPED

_REUSED = ("timeStatus", "clockOffsetSamples", "vlaService", "vlaStatus", "firewall")


def local_ipv4s() -> set:
    """IPv4 addresses of this PC (loopback included)."""
    found = {"127.0.0.1"}
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("203.0.113.1", 9))          # no packet is sent; picks the default-route NIC
            found.add(sock.getsockname()[0])
    except OSError:
        pass
    return found


def udp_port_in_use(port: int) -> bool:
    """True when something already owns the UDP port on this PC."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        try:
            sock.bind(("0.0.0.0", port))
        except OSError:
            return True
    return False


def host_room_checks(presence_port: int = PRESENCE_PORT, room_port: int = ROOM_PORT,
                     sync_port: int = SYNC_PORT, query_port: int = QUERY_PORT,
                     beacon_port: int = BEACON_PORT, listen_s: float = 3.0, extra_ips=None) -> list:

    def ports(_: Report):
        wanted = (("presence", presence_port), ("room", room_port), ("file sync", sync_port))
        # Windows takes ~2s to refuse a closed loopback port, so probe all three at once.
        with ThreadPoolExecutor(len(wanted)) as pool:
            states = list(pool.map(lambda item: tcp_probe("127.0.0.1", item[1], 2.0)[0], wanted))
        tcp = {name: state == "open" for (name, _), state in zip(wanted, states)}
        data = {**{f"tcp {n} {p}": tcp[n] for n, p in (("presence", presence_port), ("room", room_port),
                                                       ("file sync", sync_port))},
                f"udp discovery {query_port}": udp_port_in_use(query_port)}
        missing = [k for k, v in data.items() if not v]
        if not missing:
            return CheckResult("", OK, data, "All room ports are listening on this PC")
        return CheckResult("", FAIL, data, "Not listening: " + ", ".join(missing) + ". Open the room first")

    def beacon(_: Report):
        seen = None
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", beacon_port))
            except OSError as exc:
                return CheckResult("", WARN, {"port": beacon_port},
                                   f"Could not listen for announcements on UDP {beacon_port}: {exc}")
            deadline = time.monotonic() + listen_s
            while seen is None and time.monotonic() < deadline:
                sock.settimeout(max(0.05, deadline - time.monotonic()))
                try:
                    data, _addr = sock.recvfrom(65536)
                except (socket.timeout, TimeoutError):
                    break
                seen = parse_beacon(data)
        finally:
            sock.close()
        if seen is None:
            return CheckResult("", WARN, {"port": beacon_port, "listened_s": listen_s},
                               f"No room announcement heard in {listen_s:g}s: the room may be closed, "
                               "or broadcasts are blocked (clients can still join by typing your IP)")
        fields = {k: seen[k] for k in ("net_id", "host", "host_zt", "version", "pc_name") if k in seen}
        return CheckResult("", OK, fields, "Room announcement is being broadcast")

    def advertised_ip(report: Report):
        prior = report.get("hostBeacon")
        if prior is None or prior.status != OK:
            return CheckResult("", SKIPPED, summary="Skipped: no announcement to read the address from")
        advertised = prior.data.get("host", "")
        mine = local_ipv4s() | set(extra_ips or ())
        data = {"advertised": advertised, "this_pc": sorted(mine)}
        if advertised in mine:
            return CheckResult("", OK, data, f"Advertised address {advertised} belongs to this PC")
        return CheckResult("", FAIL, data,
                           f"Clients are told to use {advertised}, which is not an address of this PC. "
                           "Check which network adapter the room is using")

    reused = [c for c in default_checks() if c.name in _REUSED]
    return [Check("hostPorts", "Room ports", ports, 15),
            Check("hostBeacon", "Room announcement", beacon, listen_s + 5),
            Check("hostAdvertisedIp", "Advertised address", advertised_ip, 5), *reused]
