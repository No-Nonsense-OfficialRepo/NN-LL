"""Firewall path drift: detection (path_drift) and idempotent repair (firewall.apply_rules).

Everything is mocked: real files live in tmp_path, but no firewall rule is read or changed.
"""
import json
import os
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from lantool.diagnostics import path_drift
from lantool.diagnostics.model import FAIL, OK, SKIPPED, WARN
from silent_tunnel import firewall


def make_exe(folder, name="LAN Client.exe"):
    folder.mkdir(parents=True, exist_ok=True)
    exe = folder / name
    exe.write_bytes(b"")
    return exe


def rules_for(exe, *, enabled=True):
    return [{"name": n, "program": str(exe), "enabled": enabled, "direction": "Inbound", "action": "Allow"}
            for n in firewall.rule_names(str(exe))]


# ---- happy path ---------------------------------------------------------------------------

def test_no_drift_when_rules_point_at_the_running_exe(tmp_path):
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    result = path_drift.check(rules_for(exe), exe)
    assert result.status == OK
    assert result.data["stale"] == [] and result.data["current_rules"] == 2
    assert path_drift.stale_rules(rules_for(exe), exe) == []


def test_sibling_host_and_client_in_one_folder_are_not_drift(tmp_path):
    folder = tmp_path / "Lan Launcher V1.6"
    host, client = make_exe(folder, "LAN Host.exe"), make_exe(folder, "LAN Client.exe")
    rules = rules_for(host) + rules_for(client)
    assert path_drift.stale_rules(rules, client) == []
    assert path_drift.check(rules, client).status == OK


# ---- the four drift scenarios -------------------------------------------------------------

def test_moved_folder_leaves_rules_for_a_path_that_is_gone(tmp_path):
    old = make_exe(tmp_path / "games" / "LAN Client.exe".replace(".exe", ""), "LAN Client.exe")
    old_rules = rules_for(old)
    new = tmp_path / "usb" / "LAN"
    new.parent.mkdir(parents=True)                           # the target itself must not exist yet
    (tmp_path / "games" / "LAN Client").rename(new)          # the user moved the folder
    exe = new / "LAN Client.exe"
    stale = path_drift.stale_rules(old_rules, exe)
    assert [s["reason"] for s in stale] == ["missing", "missing"]
    result = path_drift.check(old_rules, exe)
    assert result.status == FAIL and result.data["fix"] == "firewall_repath"
    assert result.data["current_rules"] == 0


def test_copied_folder_with_the_same_version_is_other_folder(tmp_path):
    old = make_exe(tmp_path / "A" / "Lan Launcher V1.6")
    exe = make_exe(tmp_path / "B" / "Lan Launcher V1.6")
    stale = path_drift.stale_rules(rules_for(old), exe)
    assert {s["reason"] for s in stale} == {"other_folder"}
    assert path_drift.check(rules_for(old), exe).status == FAIL


def test_upgrade_v15_to_v16_flags_the_old_release_folder(tmp_path):
    old = make_exe(tmp_path / "Lan Launcher V1.5")
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    rules = rules_for(old) + rules_for(exe)
    stale = path_drift.stale_rules(rules, exe)
    assert len(stale) == 2 and {s["reason"] for s in stale} == {"older_release"}
    assert {s["program"] for s in stale} == {str(old)}
    result = path_drift.check(rules, exe)
    assert result.status == WARN                              # this copy is covered; old rules linger
    assert "older release" in result.summary
    only_old = path_drift.check(rules_for(old), exe)
    assert only_old.status == FAIL                            # upgraded but never re-prepared


def test_renamed_exe_in_the_same_folder_is_missing(tmp_path):
    folder = tmp_path / "Lan Launcher V1.6"
    before = make_exe(folder, "LAN Client 1.6.exe")
    rules = rules_for(before)
    before.rename(folder / "Game Night.exe")
    exe = folder / "Game Night.exe"
    stale = path_drift.stale_rules(rules, exe)
    assert {s["reason"] for s in stale} == {"missing"}
    assert path_drift.check(rules, exe).status == FAIL
    assert path_drift.check(rules + rules_for(exe), exe).status == WARN


def test_deleted_old_folder_is_missing_but_current_rules_keep_it_a_warning(tmp_path):
    old = make_exe(tmp_path / "Lan Launcher V1.5")
    rules_old = rules_for(old)
    (old).unlink()
    old.parent.rmdir()
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    result = path_drift.check(rules_old + rules_for(exe), exe)
    assert result.status == WARN
    assert {s["reason"] for s in result.data["stale"]} == {"missing"}


def test_disabled_current_rules_do_not_count_as_covered(tmp_path):
    old = make_exe(tmp_path / "Lan Launcher V1.5")
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    result = path_drift.check(rules_for(old) + rules_for(exe, enabled=False), exe)
    assert result.status == FAIL


# ---- edge cases ---------------------------------------------------------------------------

def test_skipped_when_not_applicable(tmp_path):
    exe = make_exe(tmp_path / "x")
    assert path_drift.check(rules_for(exe), None).status == SKIPPED       # source run
    assert path_drift.check(None, exe).status == SKIPPED                  # rules unreadable
    assert path_drift.check([], exe).status == SKIPPED                    # nothing created yet


def test_other_programs_rules_are_ignored(tmp_path):
    exe = make_exe(tmp_path / "x")
    foreign = [{"name": "Some Other App", "program": str(tmp_path / "gone.exe"), "enabled": True}]
    assert path_drift.stale_rules(foreign, exe) == []
    assert path_drift.check(foreign + rules_for(exe), exe).status == OK


def test_release_of_reads_folder_then_file_name():
    assert path_drift.release_of(r"C:\x\Lan Launcher V1.6\LAN Client.exe") == (1, 6)
    assert path_drift.release_of(r"C:\x\plain\LAN Client 1.10.exe") == (1, 10)
    assert path_drift.release_of(r"C:\x\plain\LAN Client.exe") is None
    assert path_drift.release_of(None) is None


def test_collect_reads_rules_through_one_seam(tmp_path, monkeypatch):
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    monkeypatch.setattr(firewall, "list_our_rules", lambda: rules_for(exe))
    assert path_drift.collect(exe).status == OK
    assert path_drift.collect(None).status == SKIPPED                     # source run (sys.frozen unset)


# ---- firewall helper: stale names and idempotent apply_rules ------------------------------

def test_stale_rule_names_are_ours_validated_and_never_current(tmp_path):
    old = make_exe(tmp_path / "Lan Launcher V1.5")
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    evil = {"name": "GamerUtility-0123456789abcdef-TCP'; calc; '", "program": str(tmp_path / "gone.exe")}
    rules = rules_for(old) + rules_for(exe) + [evil]
    names = firewall.stale_rule_names(str(exe), rules)
    assert names == firewall.rule_names(str(old))
    assert not set(names) & set(firewall.rule_names(str(exe)))
    assert firewall.stale_rule_names(str(exe), rules_for(exe)) == []
    assert firewall.stale_rule_names(str(exe), []) == []


def _capture_powershell(monkeypatch):
    seen = {}

    def run(args, **kwargs):
        seen["script"] = args[-1]
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(firewall.subprocess, "run", run)
    return seen


def test_apply_rules_removes_rules_for_other_paths_then_adds_current(tmp_path, monkeypatch):
    old = make_exe(tmp_path / "Lan Launcher V1.5")
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    monkeypatch.setattr(firewall, "list_our_rules", lambda: rules_for(old) + rules_for(exe))
    seen = _capture_powershell(monkeypatch)
    removed = firewall.apply_rules(str(exe))
    script = seen["script"]
    assert removed == firewall.rule_names(str(old))
    for name in firewall.rule_names(str(old)):
        assert f"Get-NetFirewallRule -Name '{name}'" in script and "Remove-NetFirewallRule" in script
    first_new = script.index("New-NetFirewallRule")
    assert all(script.index(n) < first_new for n in firewall.rule_names(str(old)))     # remove, then add
    assert all(f"New-NetFirewallRule -Name '{n}'" in script for n in firewall.rule_names(str(exe)))
    assert script.count("New-NetFirewallRule") == 2                                    # only the current exe


def test_apply_rules_is_idempotent_when_nothing_drifted(tmp_path, monkeypatch):
    exe = make_exe(tmp_path / "Lan Launcher V1.6")
    monkeypatch.setattr(firewall, "list_our_rules", lambda: rules_for(exe))
    seen = _capture_powershell(monkeypatch)
    assert firewall.apply_rules(str(exe)) == []
    assert seen["script"].count("Remove-NetFirewallRule") == 2          # only the same-name refresh
    assert seen["script"].count("New-NetFirewallRule") == 2


def test_apply_rules_still_adds_rules_when_the_listing_fails(tmp_path, monkeypatch):
    exe = make_exe(tmp_path / "x")
    monkeypatch.setattr(firewall, "list_our_rules", lambda: None)
    seen = _capture_powershell(monkeypatch)
    assert firewall.apply_rules(str(exe)) == []
    assert seen["script"].count("New-NetFirewallRule") == 2


def test_apply_rules_failure_still_raises(tmp_path, monkeypatch):
    exe = make_exe(tmp_path / "x")
    monkeypatch.setattr(firewall, "list_our_rules", lambda: [])
    monkeypatch.setattr(firewall.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="no access"))
    with pytest.raises(RuntimeError, match="no access"):
        firewall.apply_rules(str(exe))


@pytest.mark.skipif(os.name != "nt", reason="rules are read with Windows PowerShell")
def test_list_our_rules_parses_one_or_many_rows_and_failures(monkeypatch):
    rows = [{"name": "GamerUtility-0123456789abcdef-TCP", "program": "C:\\a.exe", "enabled": True}]
    for payload in (json.dumps(rows), json.dumps(rows[0])):
        monkeypatch.setattr(firewall.subprocess, "run",
                            lambda *a, _p=payload, **k: SimpleNamespace(returncode=0, stdout=_p, stderr=""))
        assert firewall.list_our_rules() == rows
    monkeypatch.setattr(firewall.subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not json", stderr=""))
    assert firewall.list_our_rules() is None
    monkeypatch.setattr(firewall.subprocess, "run", Mock(side_effect=OSError("no powershell")))
    assert firewall.list_our_rules() is None


def test_list_our_rules_ignores_non_text_output(monkeypatch):
    monkeypatch.setattr(firewall.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=Mock()))
    assert firewall.list_our_rules() is None


# ---- prepare_pc: drift reported before and after, one elevated call, idempotent -----------

def _status(stale, ready=True):
    return {"vla": True, "firewall": True, "network": True, "public": [], "ready": ready,
            "stale_rules": stale, "missing": []}


def test_prepare_pc_repairs_drift_with_one_elevated_call(tmp_path, monkeypatch):
    from silent_tunnel import prepare
    old_names = firewall.rule_names(str(tmp_path / "Lan Launcher V1.5" / "LAN Client.exe"))
    monkeypatch.setattr(prepare, "pc_status", Mock(side_effect=[_status(old_names), _status([])]))
    monkeypatch.setattr(prepare, "unblock_folder", lambda root, **k: 0)
    elevate = Mock(return_value={"steps": {"firewall": "rules added"}})
    out = prepare.prepare_pc(tmp_path / "dl", elevate=elevate, root=None)
    elevate.assert_called_once_with("prepare_pc")                 # no paths beyond the validated caller
    assert out["stale_before"] == old_names and out["stale_after"] == []
    assert out["status"]["ready"] is True


def test_prepare_pc_second_run_has_no_drift(tmp_path, monkeypatch):
    from silent_tunnel import prepare
    monkeypatch.setattr(prepare, "pc_status", Mock(side_effect=[_status([]), _status([])]))
    elevate = Mock(return_value={"steps": {"firewall": "rules added"}})
    out = prepare.prepare_pc(tmp_path / "dl", elevate=elevate, root=None)
    assert out["stale_before"] == [] and out["stale_after"] == []
    elevate.assert_called_once_with("prepare_pc")
