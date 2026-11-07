"""Prepare this PC, the LAN Helper plumbing and the explicit Host/Client entry points.

No real service, driver, firewall or network-profile change happens here: every system call is patched.
"""
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from lantool import entry
from lantool.role import detect_role
from silent_tunnel import admin_actions as aa
from silent_tunnel import backend, firewall, installer, prepare
from silent_tunnel.errors import InstallError


# ---- entry points -------------------------------------------------------------------------

def test_apply_role_pins_the_role_without_a_file_name():
    assert entry.apply_role("host", ["x.exe"]) == ["x.exe", "--host"]
    assert entry.apply_role("client", ["x.exe", "--preview"]) == ["x.exe", "--client", "--preview"]


def test_apply_role_keeps_explicit_flags_and_special_modes():
    assert entry.apply_role("host", ["x.exe", "--client"]) == ["x.exe", "--client"]
    assert entry.apply_role("host", ["x.exe", "--lan-admin-action", "p.json"]) == ["x.exe", "--lan-admin-action", "p.json"]
    assert entry.apply_role("client", ["x.exe", "--vla-diagnose"]) == ["x.exe", "--vla-diagnose"]
    assert entry.apply_role(None, ["x.exe"]) == ["x.exe"]


@pytest.mark.parametrize("role", ["host", "client"])
def test_run_sets_role_for_the_whole_process(role):
    seen = {}

    def fake_main():
        seen["role"] = detect_role()          # reads sys.argv
        return 0

    with patch.dict(sys.modules, {"lantool.qt.main": SimpleNamespace(main=fake_main)}), \
         patch.object(sys, "argv", ["LAN Totally Renamed.exe"]), \
         patch("lantool.single_instance.already_running", return_value=False):
        with pytest.raises(SystemExit) as info:
            entry.run(role)
    assert info.value.code == 0
    assert seen["role"] == role


# ---- helper exe + caller validation -------------------------------------------------------

def _frozen_in(tmp_path, monkeypatch, exe_name):
    exe = tmp_path / exe_name
    exe.write_bytes(b"")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe))
    return exe


def test_helper_executable_only_when_frozen_and_present(tmp_path, monkeypatch):
    assert aa.helper_executable() is None                       # source run
    launcher = _frozen_in(tmp_path, monkeypatch, "LAN Client 1.2.exe")
    assert aa.helper_executable() is None                       # helper not shipped
    (tmp_path / aa.HELPER_NAME).write_bytes(b"")
    assert aa.helper_executable() == tmp_path / aa.HELPER_NAME


def test_caller_program_is_ignored_outside_the_helper(tmp_path, monkeypatch):
    _frozen_in(tmp_path, monkeypatch, "LAN Client 1.2.exe")
    assert aa._caller_program({"caller_program": str(tmp_path / "other.exe")}) is None


def test_packaged_helper_accepts_only_the_host_and_client_at_the_release_root(tmp_path, monkeypatch):
    helper = tmp_path / aa.HELPER_FOLDER / aa.HELPER_NAME
    helper.parent.mkdir(parents=True)
    helper.touch()
    host = tmp_path / "Host.exe"
    host.touch()
    quick_start = tmp_path / "Quick Start.exe"
    quick_start.touch()
    monkeypatch.setattr(aa.sys, "frozen", True, raising=False)
    monkeypatch.setattr(aa.sys, "executable", str(host))
    assert aa.helper_executable() == helper
    monkeypatch.setattr(aa.sys, "executable", str(helper))
    assert aa._caller_program({"caller_program": str(host)}) == str(host.resolve())
    with pytest.raises(ValueError, match="program path"):
        aa._caller_program({"caller_program": str(quick_start)})


def test_caller_program_accepts_only_exes_beside_the_helper(tmp_path, monkeypatch):
    _frozen_in(tmp_path, monkeypatch, aa.HELPER_NAME)
    good = tmp_path / "LAN Host 1.2.exe"
    good.write_bytes(b"")
    assert aa._caller_program({"caller_program": str(good)}) == str(good.resolve())
    assert aa._caller_program({}) is None
    elsewhere = tmp_path / "sub"
    elsewhere.mkdir()
    (elsewhere / "evil.exe").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x")
    for bad in (str(elsewhere / "evil.exe"), str(tmp_path / "notes.txt"), str(tmp_path / "missing.exe"),
                str(tmp_path / aa.HELPER_NAME), "relative.exe", 7):
        with pytest.raises(ValueError):
            aa._caller_program({"caller_program": bad})


def test_launcher_firewall_uses_the_validated_caller(tmp_path, monkeypatch):
    _frozen_in(tmp_path, monkeypatch, aa.HELPER_NAME)
    client = tmp_path / "LAN Client 1.2.exe"
    client.write_bytes(b"")
    with patch.object(firewall, "apply_rules") as apply:
        aa._run_action({"action": "launcher_firewall", "caller_program": str(client)})
    apply.assert_called_once_with(str(client.resolve()))


def test_firewall_rule_names_follow_the_program_not_the_helper(tmp_path):
    a, b = tmp_path / "LAN Host.exe", tmp_path / "LAN Client.exe"
    a.write_bytes(b"")
    b.write_bytes(b"")
    assert firewall.rule_names(str(a)) != firewall.rule_names(str(b))
    assert firewall.rule_names(str(a)) == firewall.rule_names(str(a))
    assert firewall.rule_names() == firewall.rule_names(sys.executable)


# ---- prepare_pc elevated action -----------------------------------------------------------

def test_prepare_pc_action_runs_each_fixed_step(monkeypatch):
    calls = []
    monkeypatch.setattr(installer, "_service_exists", lambda: False)
    monkeypatch.setattr(aa, "_install_vla", lambda payload: calls.append(("vla", payload["path"])))
    monkeypatch.setattr(firewall, "apply_rules", lambda program=None: calls.append(("fw", program)))
    monkeypatch.setattr(aa, "_network_private", lambda idx: calls.append(("net", idx)))
    out = aa._run_action({"action": "prepare_pc", "path": "C:\\stage", "user_sid": "S", "interface_indexes": [12]})
    assert calls == [("vla", "C:\\stage"), ("fw", None), ("net", [12])]
    assert out == {"steps": {"vla": "installed", "firewall": "rules added", "network": "set to Private"}}


def test_prepare_pc_action_skips_installed_vla_and_unselected_network(monkeypatch):
    monkeypatch.setattr(installer, "_service_exists", lambda: True)
    install = Mock()
    monkeypatch.setattr(aa, "_install_vla", install)
    monkeypatch.setattr(firewall, "apply_rules", lambda program=None: None)
    out = aa._run_action({"action": "prepare_pc", "path": "C:\\stage"})
    install.assert_not_called()
    assert out["steps"] == {"vla": "already installed", "firewall": "rules added", "network": "unchanged"}
    out = aa._run_action({"action": "prepare_pc"})
    assert out["steps"]["vla"] == "skipped"


def test_network_private_rejects_bad_interface_lists():
    for bad in (None, [], ["1"], [True], [0], [1_000_000], list(range(1, 12))):
        with pytest.raises(ValueError):
            aa._network_private(bad)


# ---- unprivileged side --------------------------------------------------------------------

def test_unblock_folder_clears_flags_but_skips_game_and_data(tmp_path):
    (tmp_path / "Source").mkdir()
    (tmp_path / "Game Directory").mkdir()
    (tmp_path / "LAN Client.exe").write_bytes(b"")
    (tmp_path / "Source" / "a.dll").write_bytes(b"")
    (tmp_path / "Source" / "b.dll").write_bytes(b"")
    (tmp_path / "Game Directory" / "game.exe").write_bytes(b"")
    flagged = {str(tmp_path / "LAN Client.exe") + ":Zone.Identifier",
               str(tmp_path / "Source" / "a.dll") + ":Zone.Identifier",
               str(tmp_path / "Game Directory" / "game.exe") + ":Zone.Identifier"}
    removed = []

    def remover(path):
        if path not in flagged:
            raise FileNotFoundError(path)
        removed.append(path)

    assert prepare.unblock_folder(tmp_path, remover=remover) == 2
    assert not any("Game Directory" in p for p in removed)
    assert prepare.unblock_folder(tmp_path / "missing", remover=remover) == 0


def _status_patches(monkeypatch, *, vla, fw, public):
    monkeypatch.setattr(prepare, "_vla_installed", lambda: vla)
    monkeypatch.setattr(prepare, "firewall_rules_present", lambda: fw)
    monkeypatch.setattr(prepare, "public_profiles", lambda: public)


def test_pc_status_ready_rules(monkeypatch):
    _status_patches(monkeypatch, vla=True, fw=True, public=[])
    assert prepare.pc_status()["ready"] and prepare.pc_status()["missing"] == []
    _status_patches(monkeypatch, vla=True, fw=None, public=[])           # source run: firewall n/a
    assert prepare.pc_status()["ready"]
    _status_patches(monkeypatch, vla=False, fw=True, public=[])
    assert not prepare.pc_status()["ready"]
    _status_patches(monkeypatch, vla=True, fw=False, public=[])
    assert prepare.pc_status()["missing"] == ["LAN firewall rules"]
    _status_patches(monkeypatch, vla=True, fw=True, public=[{"name": "Net", "index": 3}])
    status = prepare.pc_status()
    assert status["ready"] and not status["network"]                     # Private is optional


def _fake_package(tmp_path):
    package = tmp_path / "pkg"
    package.mkdir()
    (package / backend.MANIFEST_NAME).write_text("{}")
    (package / "service.bin").write_bytes(b"x")
    return package


def test_prepare_pc_stages_the_package_and_uses_one_elevation(tmp_path, monkeypatch):
    package = _fake_package(tmp_path)
    states = iter([{"vla": False, "firewall": False, "network": False, "ready": False, "missing": ["x"],
                    "public": [{"name": "Net", "index": 9}]},
                   {"vla": True, "firewall": True, "network": True, "ready": True, "missing": [], "public": []}])
    monkeypatch.setattr(prepare, "pc_status", lambda: next(states))
    monkeypatch.setattr(installer, "bundled_package_path", lambda: package)
    monkeypatch.setattr(installer, "validate_package", lambda d, **k: {"files": ["service.bin"]})
    monkeypatch.setattr(installer, "_service_exists", lambda: False)
    monkeypatch.setattr(installer, "_check_shared_driver_compatibility", lambda: None)
    monkeypatch.setattr(installer, "_check_port_available", lambda: None)
    monkeypatch.setattr(installer, "_current_user_sid", lambda: "S-1-5-21-1-2-3-4")
    seen = {}

    def elevate(action, **kwargs):
        seen["action"], seen["kwargs"] = action, dict(kwargs)
        seen["staged"] = sorted(p.name for p in Path(kwargs["path"]).iterdir())
        return {"ok": True, "steps": {"vla": "installed"}}

    messages = []
    result = prepare.prepare_pc(tmp_path / "staging", messages.append, make_private=True, elevate=elevate, root=None)
    assert seen["action"] == "prepare_pc"
    assert seen["kwargs"]["user_sid"] == "S-1-5-21-1-2-3-4"
    assert seen["kwargs"]["interface_indexes"] == [9]
    assert seen["staged"] == sorted([backend.MANIFEST_NAME, "service.bin"])
    assert not Path(seen["kwargs"]["path"]).exists()                 # staging copy removed afterwards
    assert result["status"]["ready"] and result["steps"] == {"vla": "installed"}
    assert any("one prompt" in m for m in messages)


def test_prepare_pc_without_vla_needs_no_package_and_leaves_network_alone(tmp_path, monkeypatch):
    states = iter([{"vla": True, "firewall": False, "network": False, "ready": False, "missing": ["x"],
                    "public": [{"name": "Net", "index": 9}]},
                   {"vla": True, "firewall": True, "network": False, "ready": True, "missing": [], "public": []}])
    monkeypatch.setattr(prepare, "pc_status", lambda: next(states))
    elevate = Mock(return_value={"ok": True, "steps": {}})
    prepare.prepare_pc(tmp_path, elevate=elevate, root=None)           # make_private defaults to False
    elevate.assert_called_once_with("prepare_pc")


def test_prepare_pc_reports_a_missing_runtime(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "pc_status", lambda: {"vla": False, "firewall": None, "network": True,
                                                         "ready": False, "missing": ["x"], "public": []})
    monkeypatch.setattr(installer, "bundled_package_path", lambda: None)
    with pytest.raises(InstallError):
        prepare.prepare_pc(tmp_path, elevate=Mock(), root=None)


def test_prepare_pc_turns_elevation_failures_into_install_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(prepare, "pc_status", lambda: {"vla": True, "firewall": False, "network": True,
                                                         "ready": False, "missing": ["x"], "public": []})
    with pytest.raises(InstallError, match="denied"):
        prepare.prepare_pc(tmp_path, elevate=Mock(side_effect=RuntimeError("denied")), root=None)


# ---- bridge indicator ---------------------------------------------------------------------

def test_bridge_pc_indicator_text():
    from lantool.qt import bridge as bridge_mod
    B = bridge_mod.LauncherBridge
    fake = SimpleNamespace(_pc={}, publish=Mock())
    B._pc_checked(fake, {"ready": True, "network": True, "missing": []}, "")
    assert fake._pc["ready"] and fake._pc["text"] == "PC ready"
    B._pc_checked(fake, {"ready": True, "network": False, "missing": []}, "")
    assert "Public" in fake._pc["text"]
    B._pc_checked(fake, {"ready": False, "network": True, "missing": ["VLA service and driver"]}, "")
    assert fake._pc["text"] == "Not ready: VLA service and driver" and not fake._pc["ready"]
    B._pc_checked(fake, None, "boom")
    assert fake._pc["error"] == "boom" and not fake._pc["ready"]
