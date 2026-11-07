"""Host 'Check my room': probe this PC's own room the way a client would.

Reuses the client ladder against loopback (room reply, signature, ports, UDP
discovery), then adds Host-only checks: the advertised address must belong to a
real local NIC (not link-local), plus the existing firewall and clock checks.
Read-only.
"""
from __future__ import annotations
import ipaddress
import socket

from .checks import clock_offset, firewall
from .ladder import client_ladder_checks, ROOM_PORT, _usable
from .model import Check, CheckResult, Report, OK, FAIL, WARN, SKIPPED

LOOPBACK = "127.0.0.1"


def local_ipv4s() -> set:
    """IPv4 addresses of this PC (best effort, no external calls)."""
    found = set()
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            found.add(info[4][0])
    except OSError:
        pass
    for probe in ("10.255.255.255", "192.168.255.255", "172.16.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((probe, 9))
                found.add(s.getsockname()[0])
        except OSError:
            pass
    found.discard("0.0.0.0")
    return found


def host_checks(room_port: int = ROOM_PORT, ips_fn=local_ipv4s, **kw) -> list:
    """Checks for 'Check my room', in order."""
    out = client_ladder_checks(LOOPBACK, room_port=room_port, prefix="host", **kw)
    keep = {"hostTcpRoom": "Room is open", "hostRoomResponse": "Room signed reply",
            "hostPorts": "Room ports listening", "hostUdpDiscovery": "Discovery answering"}
    out = [Check(c.name, keep[c.name], c.run, c.timeout_s) for c in out if c.name in keep]

    def advertised(report: Report):
        if not _usable(report, "hostRoomResponse"):
            return CheckResult("", SKIPPED, summary="Skipped: room not answering")
        addr = str(report.get("hostRoomResponse").data["beacon"].get("host", ""))
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            return CheckResult("", FAIL, {"address": addr}, "The room advertises no valid address")
        if ip.is_link_local:
            return CheckResult("", FAIL, {"address": addr},
                               "Advertised address is link-local (169.254.x.x): this PC has no real network address")
        mine = ips_fn()
        if addr not in mine:
            return CheckResult("", WARN, {"address": addr, "local": sorted(mine)},
                               f"Advertised address {addr} is not on any adapter of this PC; "
                               "clients may be sent to the wrong network")
        return CheckResult("", OK, {"address": addr}, f"Advertising {addr}, which is on this PC")

    out.append(Check("hostAdvertisedAddress", "Advertised address", advertised, 6))
    out.append(Check("hostClockOffset", "Host clock", clock_offset, 25))
    out.append(Check("hostFirewall", "Firewall rules", firewall, 30))
    return out
