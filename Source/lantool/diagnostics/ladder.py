"""Client ladder: walk the real join path against one chosen Host, a step per check.

Each step names the stage that would fail a real join, so the report points at
the first broken rung instead of a generic "couldn't join". Steps that depend on
an earlier one are SKIPPED when it failed. Read-only: it only opens plain TCP
connections, one HTTP GET and one UDP query to the Host.

Not covered here (needs a live VLA network): the VLA join, address assignment and
the overlay ping. Those stay with the normal join and the local checks.
"""
from __future__ import annotations
import json
import socket
import time

from .._version import __version__, __proto__ as PROTO_VERSION
from ..netcore import compat
from ..netcore.beacon import REPLAY_WINDOW_S, parse_beacon
from ..netcore.discovery import QUERY, QUERY_PORT
from ..trust.signing import verify_obj
from .model import Check, CheckResult, Report, OK, WARN, FAIL, SKIPPED

ROOM_PORT = 47802
PRESENCE_PORT = 47800
SYNC_PORT = 47803
CLOCK_WARN_S = 10
MAX_RESPONSE = 70000

# Fields that are safe and useful to show; signatures and keys stay out of reports.
_PUBLIC_FIELDS = ("v", "net_id", "host", "host_zt", "presence_port", "planet_port",
                  "sync_port", "version", "proto", "ts", "pc_name")


def tcp_probe(address: str, port: int, timeout: float = 4.0) -> tuple:
    """Return (state, detail); state is open, refused, timeout or unreachable."""
    try:
        with socket.create_connection((address, port), timeout):
            return "open", ""
    except ConnectionRefusedError:
        return "refused", "connection refused"
    except (socket.timeout, TimeoutError):
        return "timeout", f"no answer in {timeout:g}s"
    except OSError as exc:
        return "unreachable", str(exc).strip() or type(exc).__name__


def _skipped(why: str) -> CheckResult:
    return CheckResult("", SKIPPED, summary=f"Skipped: {why}")


def _usable(report: Report, name: str) -> bool:
    prior = report.get(name)
    return prior is not None and prior.status in (OK, WARN)


def _http_room(address: str, port: int, timeout: float) -> bytes:
    """Fetch the raw /room response (HTTP/1.0, closes when done)."""
    deadline = time.monotonic() + timeout
    with socket.create_connection((address, port), timeout) as sock:
        sock.sendall(b"GET /room HTTP/1.0\r\n\r\n")
        chunks, size = [], 0
        while size <= MAX_RESPONSE:
            sock.settimeout(max(0.1, deadline - time.monotonic()))
            chunk = sock.recv(8192)
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
    return b"".join(chunks)


def client_ladder_checks(address: str, room_port: int = ROOM_PORT, query_port: int = QUERY_PORT,
                         udp_timeout: float = 3.0, tcp_timeout: float = 4.0,
                         trusted_pub: str | None = None, prefix: str = "ladder") -> list:
    """Checks to run, in order, against the Host at `address`.

    trusted_pub: the Host key this PC pinned (room key / earlier join); when given,
    the Host's signing key must match it. The key itself never enters the report.
    """
    seen = {}

    def tcp_room(_: Report):
        state, detail = tcp_probe(address, room_port, tcp_timeout)
        data = {"address": address, "port": room_port, "state": state, "detail": detail}
        if state == "open":
            return CheckResult("", OK, data, f"Host answers on port {room_port}")
        causes = {
            "refused": "The PC is reachable but no room is open there (or its firewall rejects the port)",
            "timeout": "No answer: wrong IP, Host offline, firewall blocking, or Wi-Fi client isolation",
            "unreachable": "No route to the Host: check both PCs are on the same network",
        }
        return CheckResult("", FAIL, data, causes.get(state, detail))

    def room_response(report: Report):
        if not _usable(report, f"{prefix}TcpRoom"):
            return _skipped("Host port not reachable")
        raw = _http_room(address, room_port, tcp_timeout + 2)
        head, _, body = raw.partition(b"\r\n\r\n")
        if not head.startswith(b"HTTP/1.0 200 ") and not head.startswith(b"HTTP/1.1 200 "):
            return CheckResult("", FAIL, {"status_line": head.split(b"\r\n")[0][:80].decode("latin-1")},
                               "The Host answered, but not with a room (wrong program on this port?)")
        try:
            obj = json.loads(body)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            return CheckResult("", FAIL, None, "The Host's room reply is malformed. Both PCs should run the same version")
        signer = obj.get("host_pub")
        if not isinstance(signer, str) or not verify_obj(signer, obj):
            return CheckResult("", FAIL, None, "The Host's room reply has an invalid signature, so it is not trusted")
        seen["pub"] = signer
        try:
            skew = round(time.time() - float(obj.get("ts", 0)), 1)
        except (TypeError, ValueError):
            return CheckResult("", FAIL, None, "The Host's room reply has no valid timestamp")
        data = {"beacon": {k: obj[k] for k in _PUBLIC_FIELDS if k in obj}, "skew_s": skew}
        return CheckResult("", OK, data, "Signed room reply received and verified")

    def identity(report: Report):
        if not _usable(report, f"{prefix}RoomResponse"):
            return _skipped("no room reply to check")
        if not trusted_pub:
            return CheckResult("", OK, {"pinned": False}, "No pinned Host key to compare (first join or typed IP)")
        if seen.get("pub") != trusted_pub:
            return CheckResult("", FAIL, {"pinned": True, "match": False},
                               "This Host's key does not match the room you joined before. Wrong room key, "
                               "or a different PC is answering at this IP")
        return CheckResult("", OK, {"pinned": True, "match": True}, "Host identity matches the pinned room key")

    def clock(report: Report):
        if not _usable(report, f"{prefix}RoomResponse"):
            return _skipped("no room reply to compare")
        skew = report.get(f"{prefix}RoomResponse").data["skew_s"]
        size = abs(skew)
        side = "ahead of" if skew > 0 else "behind"
        data = {"skew_s": skew, "limit_s": REPLAY_WINDOW_S}
        if size > REPLAY_WINDOW_S:
            return CheckResult("", FAIL, data,
                               f"This PC's clock is {size:g}s {side} the Host; joins are rejected beyond {REPLAY_WINDOW_S}s. Fix the time on the wrong PC")
        if size > CLOCK_WARN_S:
            return CheckResult("", WARN, data, f"Clock is {size:g}s {side} the Host (limit {REPLAY_WINDOW_S}s)")
        return CheckResult("", OK, data, f"Clocks agree (within {max(size, 1):g}s)")

    def ports(report: Report):
        if not _usable(report, f"{prefix}RoomResponse"):
            return _skipped("no room reply to read ports from")
        beacon = report.get(f"{prefix}RoomResponse").data["beacon"]
        targets = {"presence": beacon.get("presence_port") or PRESENCE_PORT,
                   "file sync": beacon.get("sync_port") or SYNC_PORT}
        results = {name: dict(zip(("state", "detail"), tcp_probe(address, port, tcp_timeout)), port=port)
                   for name, port in targets.items()}
        if results["presence"]["state"] != "open":
            return CheckResult("", FAIL, results,
                               f"Presence port {targets['presence']} is blocked; the player list and game status will not work")
        if results["file sync"]["state"] != "open":
            return CheckResult("", WARN, results,
                               f"File-sync port {targets['file sync']} is blocked; game downloads may fail")
        return CheckResult("", OK, results, "Presence and file-sync ports reachable")

    def version(report: Report):
        if not _usable(report, f"{prefix}RoomResponse"):
            return _skipped("no room reply to read the version from")
        beacon = report.get(f"{prefix}RoomResponse").data["beacon"]
        host_version = str(beacon.get("version", ""))
        host_proto = compat.proto_of(beacon)
        ok, level, message, hint = compat.check(host_version, host_proto, __version__, PROTO_VERSION)
        data = {"host": host_version, "this_pc": __version__,
                "host_proto": host_proto, "this_pc_proto": PROTO_VERSION, "level": level}
        status = OK if level == compat.OK else (FAIL if level == compat.BLOCK else WARN)
        text = message if not hint or level == compat.OK else f"{message} {hint}"
        return CheckResult("", status, data, text)

    def udp_discovery(_: Report):
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.settimeout(udp_timeout)
            sock.sendto(QUERY, (address, query_port))
            try:
                data, _addr = sock.recvfrom(65536)
            except (socket.timeout, TimeoutError):
                return CheckResult("", WARN, {"port": query_port},
                                   "No UDP discovery reply; automatic discovery will not find this Host, but typing its IP still works")
            except OSError as exc:
                # Windows reports an ICMP 'port unreachable' as a connection reset.
                return CheckResult("", WARN, {"port": query_port, "detail": str(exc).strip()},
                                   "The Host refused the UDP discovery port (room closed or firewall rejecting); "
                                   "automatic discovery will not find it, but typing its IP still works")
        if parse_beacon(data) is None:
            return CheckResult("", WARN, {"port": query_port},
                               "UDP discovery reply was not valid or fresh (check the clocks)")
        return CheckResult("", OK, {"port": query_port}, "UDP discovery works")

    return [
        Check(f"{prefix}TcpRoom", "Reach Host", tcp_room, tcp_timeout + 2),
        Check(f"{prefix}RoomResponse", "Host room reply", room_response, tcp_timeout + 4),
        Check(f"{prefix}Identity", "Host identity", identity, 3),
        Check(f"{prefix}Clock", "Clock agreement", clock, 3),
        Check(f"{prefix}Ports", "Host ports", ports, 2 * tcp_timeout + 3),
        Check(f"{prefix}Version", "Version match", version, 3),
        Check(f"{prefix}UdpDiscovery", "UDP discovery", udp_discovery, udp_timeout + 3),
    ]
