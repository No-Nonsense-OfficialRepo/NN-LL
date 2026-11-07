"""Phase 4 step 3: safe Fix buttons (fix map, network-profile check, admin action guards, runFix)."""
from types import SimpleNamespace

import pytest

from lantool.diagnostics import checks
from lantool.diagnostics.model import CheckResult, Report, OK, WARN, FAIL
from lantool.diagnostics.service import fix_for, summarize_rows
from lantool.qt import bridge as bridge_mod

B = bridge_mod.LauncherBridge


def test_fix_map_only_for_warn_or_fail():
    assert fix_for(CheckResult("networkProfile", WARN)) == ("", "")
    assert fix_for(CheckResult("networkProfile", OK)) == ("", "")
    assert fix_for(CheckResult("vlaService", WARN))[0] == "restartVla"
    assert fix_for(CheckResult("vlaService", FAIL)) == ("", "")  # not installed: restart cannot help
    assert fix_for(CheckResult("firewall", FAIL)) == ("repairLan", "Repair LAN")
    assert fix_for(CheckResult("firewall", OK)) == ("", "")
    assert fix_for(CheckResult("peers", FAIL)) == ("", "")


def test_rows_carry_fix_fields():
    rows = summarize_rows(Report("u", "c", [CheckResult("networkProfile", WARN, summary="Public")]))
    assert rows[0]["fix"] == "" and rows[0]["fixLabel"] == ""


def test_network_profile_check_flags_public(monkeypatch):
    monkeypatch.setattr(checks, "powershell_json", lambda *a, **k: [
        {"InterfaceIndex": 7, "name": "Home", "category": "Public"},
        {"InterfaceIndex": 9, "name": "Lab", "category": "Private"}])
    r = checks.network_profile(Report("u", "c"))
    assert r.status == OK and r.data["public"][0]["InterfaceIndex"] == 7


def test_network_profile_check_ok_when_private(monkeypatch):
    monkeypatch.setattr(checks, "powershell_json", lambda *a, **k: {"InterfaceIndex": 9, "name": "Lab", "category": "Private"})
    assert checks.network_profile(Report("u", "c")).status == OK


@pytest.mark.parametrize("bad", [None, [], ["1; calc"], [True], [0], [-3], list(range(1, 20))])
def test_admin_action_rejects_bad_interface_list(bad):
    from silent_tunnel.admin_actions import _run_action
    with pytest.raises(ValueError):
        _run_action({"action": "network_private", "interface_indexes": bad})


def _fake(**kw):
    errors = []
    me = SimpleNamespace(_preview=False, _wiping=False, _closing=False, busy=False, _diag={}, _public_profiles=[], publish=lambda: None,
                         after=lambda ms, cb, *a: cb(*a))
    me.__dict__.update(kw)
    return me


def test_run_fix_unknown_id_does_nothing():
    me = _fake()
    B.runFix(me, "formatDisk")
    assert me._diag == {}


def test_run_fix_private_without_public_profile_reports_error():
    me = _fake()
    B.runFix(me, "setPrivate")
    assert "connection check" in me._diag["error"]


def test_run_fix_private_cancelled_runs_nothing(monkeypatch):
    me = _fake(_public_profiles=[{"InterfaceIndex": 7, "name": "Home"}])
    monkeypatch.setattr(bridge_mod.QMessageBox, "question",
                        lambda *a, **k: bridge_mod.QMessageBox.StandardButton.Cancel)
    called = []
    import silent_tunnel.admin_actions as aa
    monkeypatch.setattr(aa, "run_elevated", lambda *a, **k: called.append(a))
    B.runFix(me, "setPrivate")
    assert called == []


def test_run_fix_repair_lan_uses_firewall_action(monkeypatch):
    import silent_tunnel.admin_actions as aa
    seen = []
    monkeypatch.setattr(aa, "run_elevated", lambda action, **kw: seen.append(action) or {"ok": True})
    started = []
    me = _fake(_start_diag=lambda mc: started.append(mc), _fix_done=lambda r, e: B._fix_done(me, r, e))

    class Inline:
        def __init__(self, target, **kw): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(bridge_mod.threading, "Thread", Inline)
    B.runFix(me, "repairLan")
    assert seen == ["launcher_firewall"] and started == [None]


def test_fix_done_rechecks_on_success_and_reports_failure():
    started = []
    me = _fake(_start_diag=lambda mc: started.append(mc))
    B._fix_done(me, {"ok": True}, "")
    assert started == [None]
    B._fix_done(me, {"ok": False, "error": "denied"}, "")
    assert "denied" in me._diag["error"] and started == [None]
