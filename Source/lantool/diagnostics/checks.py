"""Concrete checks ported from Connection Check.ps1 (read-only; no secrets exported).

Every function takes the Report so far and returns plain data (or a CheckResult
when it wants to set a status). Windows-only probes degrade to an error entry
elsewhere. Side-effect seams (`run_cmd`, `http_get`) are module-level so tests
can replace them.
"""
from __future__ import annotations
import hashlib
import json
import os
import platform
import secrets
import socket
import struct
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from .model import Check, CheckResult, Report, OK, WARN, FAIL, SKIPPED

VLA_API = "http://127.0.0.1:47993/"
VLA_SERVICE = "LanLauncherVLA"
ROOM_PORTS = (47800, 47802, 47803, 47805, 47993)
STUN_SERVERS = (("Cloudflare", "stun.cloudflare.com", 3478), ("Google", "stun.l.google.com", 19302))
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_cmd(args, timeout=10) -> str:
    p = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                       creationflags=_NO_WINDOW, errors="replace")
    return (p.stdout + p.stderr).strip()


def powershell(script: str, timeout=15) -> str:
    return run_cmd(["powershell", "-NoProfile", "-NonInteractive", "-Command", script], timeout)


def powershell_json(script: str, timeout=15):
    p = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command",
         f"$ErrorActionPreference='Stop'; ({script}) | ConvertTo-Json -Depth 5 -Compress"],
        capture_output=True, text=True, timeout=timeout, creationflags=_NO_WINDOW, errors="replace")
    out = p.stdout.strip()
    try:
        return json.loads(out) if out else []
    except ValueError:
        detail = (p.stderr or out).strip().splitlines()
        raise RuntimeError("PowerShell returned no JSON: " + (detail[0][:200] if detail else "empty output")) from None


def _as_list(v):
    return v if isinstance(v, list) else ([] if v in (None, "") else [v])


def _token_path() -> Path:
    return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "LAN Launcher" / "VLA" / "authtoken.secret"


def http_get(route: str, timeout=5):
    token = _token_path().read_text(encoding="utf-8").strip()
    req = urllib.request.Request(VLA_API + route, headers={"X-ZT1-Auth": token})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))      # never use a proxy for localhost
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# -- checks -----------------------------------------------------------------------
def windows(_: Report):
    return {"system": platform.system(), "release": platform.release(), "version": platform.version(),
            "machine": platform.machine()}


def time_status(_: Report):
    return run_cmd(["w32tm", "/query", "/status"])


def clock_offset(_: Report):
    return run_cmd(["w32tm", "/stripchart", "/computer:time.windows.com", "/dataonly", "/samples:3"], 20)


def vla_service(_: Report):
    rows = _as_list(powershell_json(
        f"Get-CimInstance Win32_Service -Filter \"Name='{VLA_SERVICE}'\" | "
        "Select-Object @{n='state';e={[string]$_.State}},@{n='path';e={[string]$_.PathName}}"))
    if not rows:
        return CheckResult("vlaService", FAIL, summary="VLA service is not installed")
    state = rows[0].get("state")
    return CheckResult("vlaService", OK if state == "Running" else WARN, rows[0], f"VLA service {state}")


def network_profile(_: Report):
    """Flag Public profiles for diagnosis; the launcher supports them with inbound rules."""
    rows = _as_list(powershell_json(
        "Get-NetConnectionProfile | Select-Object InterfaceIndex,"
        "@{n='name';e={[string]$_.Name}},@{n='category';e={[string]$_.NetworkCategory}}"))
    public = [r for r in rows if str(r.get('category')) in ('Public', '0')]
    if public:
        names = ", ".join(str(r.get('name')) for r in public)
        return CheckResult("networkProfile", OK, {"profiles": rows, "public": public},
                           f"Public network ({names}) is supported; if connections fail, check Windows and third-party firewall rules")
    return CheckResult("networkProfile", OK, {"profiles": rows}, "Network profile is Private/Domain")


def vla_status(_: Report):
    s = http_get("status")
    cfg = (s.get("config") or {}).get("settings") or {}
    data = {"online": s.get("online"), "node": s.get("address"), "version": s.get("version"),
            "tcpFallbackActive": s.get("tcpFallbackActive"), "listeningOn": cfg.get("listeningOn"),
            "surfaceAddresses": cfg.get("surfaceAddresses"),
            "tcpFallbackAllowed": cfg.get("allowTcpFallbackRelay"), "portMapping": cfg.get("portMappingEnabled")}
    if not s.get("online"):
        return CheckResult("vlaStatus", WARN, data, "VLA reports offline")
    if s.get("tcpFallbackActive"):
        return CheckResult("vlaStatus", WARN, data,
                           "VLA online but using TCP fallback relay (UDP blocked?); expect higher latency")
    return CheckResult("vlaStatus", OK, data, "VLA online")


def networks(_: Report):
    return [{"id": str(n.get("id")), "status": str(n.get("status")), "portError": n.get("portError"),
             "addresses": n.get("assignedAddresses") or []} for n in _as_list(http_get("network"))]


def peers(_: Report):
    return [{"node": p.get("address"), "role": p.get("role"), "latency": p.get("latency"),
             "paths": [{"address": str(x.get("address")), "active": bool(x.get("active")),
                        "lastReceive": x.get("lastReceive"), "lastSend": x.get("lastSend")}
                       for x in (p.get("paths") or [])]} for p in _as_list(http_get("peer"))]


def peer_path_verdict(rows: list):
    """Classify peer rows: returns (status, summary). Relay roles are not counted as room peers."""
    leaves = [p for p in rows if str(p.get("role") or "").upper() not in ("PLANET", "MOON")]
    if not leaves:
        return SKIPPED, "No other peers in the room yet"
    direct = [p for p in leaves if any(x.get("active") for x in p.get("paths") or [])]
    if not direct:
        return WARN, "No direct peer paths: traffic is relayed or peers are unreachable"
    if len(direct) < len(leaves):
        return WARN, f"{len(direct)} of {len(leaves)} peers have a direct path"
    return OK, f"All {len(leaves)} peers have a direct path"


def peer_paths(_: Report):
    rows = peers(_)
    status, summary = peer_path_verdict(rows)
    return CheckResult("peerPaths", status, rows, summary)


def room_listeners(_: Report):
    ports = ",".join(map(str, ROOM_PORTS))
    return _as_list(powershell_json(
        f"Get-NetTCPConnection -State Listen | Where-Object LocalPort -in {ports} | "
        "Select-Object @{n='address';e={[string]$_.LocalAddress}},@{n='port';e={[int]$_.LocalPort}},"
        "@{n='process';e={[int]$_.OwningProcess}}"))


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest().upper()


def running_launchers(_: Report):
    rows = _as_list(powershell_json(
        "Get-CimInstance Win32_Process | Where-Object Name -match '^LAN (Host|Client).*\\.exe$' | "
        "Select-Object Name,ExecutablePath"))
    out = []
    for r in rows:
        path = r.get("ExecutablePath") or ""
        try:
            digest = _sha256(path) if path else ""
        except OSError:
            digest = ""
        out.append({"name": r.get("Name"), "path": path, "sha256": digest})
    return out


def firewall(report: Report):
    programs = [str(Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "LAN Launcher/VLA/vla-service.exe")]
    prev = report.get("runningLaunchers")
    programs += [x["path"] for x in (prev.data if prev and prev.data else []) if x.get("path")]
    quoted = ",".join("'" + p.replace("'", "''") + "'" for p in dict.fromkeys(programs))
    return _as_list(powershell_json(
        f"foreach($p in @({quoted})){{ Get-NetFirewallApplicationFilter -Program $p -EA SilentlyContinue | "
        "Get-NetFirewallRule -EA SilentlyContinue | Where-Object Enabled -eq True | ForEach-Object { "
        "$a=$_|Get-NetFirewallApplicationFilter; $pt=$_|Get-NetFirewallPortFilter; $s=$_|Get-NetFirewallAddressFilter; "
        "[pscustomobject]@{name=$_.DisplayName;action=[string]$_.Action;direction=[string]$_.Direction;"
        "program=$a.Program;protocol=$pt.Protocol;localPort=$pt.LocalPort;remoteAddress=$s.RemoteAddress} } }", 25))


def parse_stun(data: bytes, txid: bytes):
    """Return 'ip:port' from a STUN binding response, or raise ValueError."""
    if len(data) < 20 or data[0] != 1 or data[1] != 1 or data[8:20] != txid:
        raise ValueError("Invalid or unmatched STUN response")
    end = min(len(data), 20 + struct.unpack(">H", data[2:4])[0])
    off = 20
    while off + 4 <= end:
        kind, length = struct.unpack(">HH", data[off:off + 4])
        if off + 4 + length > end:
            raise ValueError("Truncated STUN attribute")
        if kind == 0x0020 and length >= 8 and data[off + 5] == 1:
            port = struct.unpack(">H", data[off + 6:off + 8])[0] ^ 0x2112
            ip = ".".join(str(b ^ c) for b, c in zip(data[off + 8:off + 12], b"\x21\x12\xa4\x42"))
            return f"{ip}:{port}"
        off += 4 + ((length + 3) // 4) * 4
    raise ValueError("No IPv4 mapping in response")


def udp_nat_probe(_: Report):
    targets = []
    for name, host, port in STUN_SERVERS:
        ip = next(a[4][0] for a in socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_DGRAM))
        targets.append((name, ip, port))
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(4)
    results = []
    try:
        sock.bind(("", 0))
        local = sock.getsockname()[1]
        for name, ip, port in (targets[0], targets[1], targets[0]):      # same socket: reveals NAT mapping changes
            row = {"server": name, "localPort": local, "destination": f"{ip}:{port}"}
            try:
                txid = secrets.token_bytes(12)
                sock.sendto(b"\x00\x01\x00\x00\x21\x12\xa4\x42" + txid, (ip, port))
                data, addr = sock.recvfrom(2048)
                if addr[0] != ip:
                    raise ValueError("Invalid or unmatched STUN response")
                row["mapped"] = parse_stun(data, txid)
            except Exception as exc:
                row["error"] = str(exc) or type(exc).__name__
            results.append(row)
    finally:
        sock.close()
    ok = [r for r in results if "mapped" in r]
    ports = {r["mapped"].rsplit(":", 1)[1] for r in ok}
    if not ok:
        return CheckResult("udpNatProbe", FAIL, results, "No STUN replies: UDP appears blocked. Allow outbound UDP (ports 3478, 19302, 9993) in the "
                           "firewall/router, or rely on the TCP fallback relay (slower)")
    if len(ports) > 1:
        return CheckResult("udpNatProbe", WARN, results, "NAT mapping changes per destination (symmetric NAT): direct peer paths may fail; "
                           "enable port forwarding/UPnP on the router or expect relayed traffic")
    return CheckResult("udpNatProbe", OK, results, "UDP reachable, stable NAT mapping")


def join_timing_log() -> Path:
    return Path(tempfile.gettempdir()) / "lanlauncher-join-timings.log"


def summarize_join_timings(lines) -> str:
    """One line for the report: how many timed joins, failures, slowest, and the latest outcome."""
    import re
    rows = []
    for line in lines:
        ev = re.search(r"event=(\S+)", line)
        if not ev:
            continue
        dur = re.search(r"duration_s=([\d.]+)", line)
        out = re.search(r"outcome=(.*)$", line)
        rows.append((ev[1], float(dur[1]) if dur else None, (out[1].strip() if out else "")))
    timed = [r for r in rows if r[1] is not None]
    if not timed:
        return "No timed joins recorded"
    failed = [r for r in timed if r[2] and not r[2].startswith(("connected", "ok", "joined"))]
    slow = max(timed, key=lambda r: r[1])
    last = timed[-1]
    text = (f"{len(timed)} timed events, {len(failed)} not connected; slowest {slow[0]} {slow[1]:.1f}s; "
            f"latest {last[0]} {last[1]:.1f}s ({last[2] or 'no outcome'})")
    if failed:
        text += f"; last failure {failed[-1][0]}: {failed[-1][2][:80]}"
    return text


def recent_join_timing(_: Report):
    log = join_timing_log()
    if not log.exists():
        return CheckResult("recentJoinTiming", OK, [], "No join timings recorded yet")
    lines = log.read_text(encoding="utf-8", errors="replace").splitlines()[-70:]
    return CheckResult("recentJoinTiming", OK, lines, summarize_join_timings(lines))


def path_drift_check(report):
    from .path_drift import collect
    return collect()


def data_dir_check(report):
    from ..appdirs import data_dir_problem
    problem = data_dir_problem()
    if problem:
        return CheckResult("dataDir", FAIL, summary=problem)
    return CheckResult("dataDir", OK, summary="Data folder is writable")


def default_checks() -> list:
    return [
        Check("windows", "Windows", windows),
        Check("timeStatus", "Time service", time_status),
        Check("clockOffsetSamples", "Clock offset", clock_offset, 25),
        Check("networkProfile", "Network profile", network_profile),
        Check("vlaService", "VLA service", vla_service),
        Check("vlaStatus", "VLA status", vla_status),
        Check("networks", "Room networks", networks),
        Check("peers", "Peers", peers),
        Check("peerPaths", "Peer paths", peer_paths),
        Check("roomListeners", "Room ports", room_listeners),
        Check("runningLaunchers", "Running launchers", running_launchers, 30),
        Check("firewall", "Firewall rules", firewall, 30),
        Check("pathDrift", "Install location", path_drift_check, 30),
        Check("dataDir", "Data folder", data_dir_check),
        Check("udpNatProbe", "UDP / NAT probe", udp_nat_probe, 20),
        Check("recentJoinTiming", "Recent join timings", recent_join_timing),
    ]
