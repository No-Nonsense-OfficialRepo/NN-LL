import struct

import pytest

from lantool.diagnostics import checks, run_checks, OK, WARN, FAIL
from lantool.diagnostics.model import Report


def _stun_response(txid, ip=(203, 0, 113, 7), port=40000):
    xport = struct.pack(">H", port ^ 0x2112)
    xip = bytes(b ^ c for b, c in zip(ip, b"\x21\x12\xa4\x42"))
    attr = struct.pack(">HH", 0x0020, 8) + b"\x00\x01" + xport + xip
    return b"\x01\x01" + struct.pack(">H", len(attr)) + b"\x21\x12\xa4\x42" + txid + attr


def test_parse_stun_ok():
    tx = bytes(range(12))
    assert checks.parse_stun(_stun_response(tx), tx) == "203.0.113.7:40000"


def test_parse_stun_rejects_wrong_transaction():
    with pytest.raises(ValueError):
        checks.parse_stun(_stun_response(bytes(12)), bytes(range(12)))


def test_parse_stun_rejects_truncated_attribute():
    tx = bytes(12)
    bad = b"\x01\x01\x00\x08\x21\x12\xa4\x42" + tx + struct.pack(">HH", 0x0020, 64)
    with pytest.raises(ValueError):
        checks.parse_stun(bad, tx)


def test_default_checks_cover_all_ps1_sections_with_unique_names():
    names = [c.name for c in checks.default_checks()]
    assert len(names) == len(set(names))
    for n in ("windows", "timeStatus", "vlaService", "vlaStatus", "networks", "peers", "roomListeners",
              "runningLaunchers", "firewall", "udpNatProbe", "recentJoinTiming", "peerPaths"):
        assert n in names


def test_vla_status_offline_is_warn_and_secrets_never_leak(monkeypatch):
    monkeypatch.setattr(checks, "http_get", lambda route, timeout=5: {
        "online": False, "address": "abcdef1234", "version": "1.0",
        "config": {"settings": {"listeningOn": [9993]}}, "authtoken": "SECRET123"})
    rep = run_checks([checks.Check("vlaStatus", "VLA", checks.vla_status)])
    r = rep.get("vlaStatus")
    assert r.status == WARN and "SECRET123" not in str(r.to_dict())


def test_missing_token_file_becomes_error_not_crash(monkeypatch):
    monkeypatch.setattr(checks, "_token_path", lambda: checks.Path("Z:/definitely/missing.secret"))
    rep = run_checks([checks.Check("networks", "N", checks.networks)])
    assert rep.get("networks").status == "error"


def test_peer_path_verdict_classifies_direct_relayed_and_empty():
    direct = {"role": "LEAF", "paths": [{"active": True}]}
    relayed = {"role": "LEAF", "paths": [{"active": False}]}
    planet = {"role": "PLANET", "paths": [{"active": True}]}
    assert checks.peer_path_verdict([planet])[0] == "skipped"      # alone in the room: not a problem
    assert checks.peer_path_verdict([])[0] == "skipped"
    assert checks.peer_path_verdict([planet, relayed])[0] == WARN
    assert checks.peer_path_verdict([relayed])[1].startswith("No direct")
    assert checks.peer_path_verdict([direct, relayed])[1] == "1 of 2 peers have a direct path"
    assert checks.peer_path_verdict([planet, direct])[0] == OK


def test_vla_status_tcp_fallback_is_warn(monkeypatch):
    monkeypatch.setattr(checks, "http_get", lambda route, timeout=5: {
        "online": True, "address": "abcdef1234", "tcpFallbackActive": True, "config": {"settings": {}}})
    r = run_checks([checks.Check("vlaStatus", "VLA", checks.vla_status)]).get("vlaStatus")
    assert r.status == WARN and "TCP fallback" in r.summary


def test_peer_paths_check_uses_peer_rows(monkeypatch):
    monkeypatch.setattr(checks, "http_get", lambda route, timeout=5: [
        {"address": "a", "role": "LEAF", "latency": 20, "paths": [{"address": "1.2.3.4/9993", "active": True}]}])
    r = run_checks([checks.Check("peerPaths", "P", checks.peer_paths)]).get("peerPaths")
    assert r.status == OK


def test_firewall_reuses_launcher_paths(monkeypatch):
    seen = {}
    monkeypatch.setattr(checks, "powershell_json", lambda s, t=15: seen.setdefault("s", s) and [])
    rep = Report("u", "c")
    from lantool.diagnostics.model import CheckResult
    rep.results.append(CheckResult("runningLaunchers", OK, [{"path": r"C:\Games\LAN Host.exe"}]))
    checks.firewall(rep)
    assert r"C:\Games\LAN Host.exe" in seen["s"]
