"""WP-A: portable data paths, data-folder health (describe / data_dir_problem) and the portable wipe.

Everything runs against tmp dirs (names with spaces and brackets); nothing is wiped, installed or elevated.
"""
import errno
import re
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from lantool import appdirs
from silent_tunnel import store, wipe
from contextlib import nullcontext


@pytest.fixture(autouse=True)
def isolate_system_profile_recovery(monkeypatch):
    monkeypatch.setattr(wipe.profile_records, 'transaction', nullcontext)
    monkeypatch.setattr(wipe.profile_records, '_restore_unlocked', lambda: None)


def _app(tmp_path, portable, name="USB Stick (E)"):
    root = tmp_path / name / "LAN Launcher v1.6"
    root.mkdir(parents=True)
    if portable:
        (root / "portable.flag").write_text("")
    return root


def _env(tmp_path):
    return {"LOCALAPPDATA": str(tmp_path / "Local App Data")}


# --- describe() -----------------------------------------------------------------------------

def test_describe_non_portable_with_spaces(tmp_path):
    root = _app(tmp_path, portable=False)
    info = appdirs.describe(root, _env(tmp_path))
    assert set(info) == {"portable", "data_dir", "writable", "free_mb"}
    assert info["portable"] is False
    assert info["data_dir"] == str(tmp_path / "Local App Data" / "LanTool")
    assert info["writable"] is True            # nearest existing ancestor (tmp_path) is writable
    assert isinstance(info["free_mb"], int) and info["free_mb"] >= 0


def test_describe_portable_with_spaces(tmp_path):
    root = _app(tmp_path, portable=True)
    info = appdirs.describe(root, _env(tmp_path))
    assert info["portable"] is True
    assert info["data_dir"] == str(root / "LanTool-data")
    assert info["writable"] is True


def test_describe_does_not_create_the_data_dir_or_leave_probe_files(tmp_path):
    root = _app(tmp_path, portable=True)
    appdirs.describe(root, _env(tmp_path))
    assert not (root / "LanTool-data").exists()
    assert not list(root.glob(".lantool-probe-*"))


def test_describe_probes_existing_data_dir(tmp_path):
    root = _app(tmp_path, portable=True)
    (root / "LanTool-data").mkdir()
    appdirs.describe(root, _env(tmp_path))
    assert list((root / "LanTool-data").iterdir()) == []


def test_describe_readonly_and_unknown_free_space(tmp_path):
    root = _app(tmp_path, portable=True)
    with patch.object(appdirs, "_probe_write", return_value="denied"), \
            patch.object(appdirs, "_free_mb", return_value=None):
        info = appdirs.describe(root, _env(tmp_path))
    assert info["writable"] is False and info["free_mb"] is None


def test_describe_never_raises(tmp_path):
    root = _app(tmp_path, portable=False)
    with patch.object(appdirs, "_inspect", side_effect=RuntimeError("boom")):
        info = appdirs.describe(root, _env(tmp_path))
    assert info["writable"] is False and info["free_mb"] is None
    assert info["data_dir"].endswith("LanTool")


# --- data_dir_problem() ---------------------------------------------------------------------

def test_no_problem_on_a_healthy_folder(tmp_path):
    assert appdirs.data_dir_problem(_app(tmp_path, True), _env(tmp_path)) is None
    assert appdirs.data_dir_problem(_app(tmp_path, False, "Other Copy"), _env(tmp_path)) is None


def test_readonly_portable_names_the_folder_and_the_fix(tmp_path):
    root = _app(tmp_path, portable=True)
    with patch.object(appdirs, "_probe_write", return_value="denied"):
        msg = appdirs.data_dir_problem(root, _env(tmp_path))
    assert str(root / "LanTool-data") in msg
    assert "read-only" in msg and "portable.flag" in msg


def test_readonly_non_portable_does_not_mention_portable_flag_as_the_fix(tmp_path):
    root = _app(tmp_path, portable=False)
    with patch.object(appdirs, "_probe_write", return_value="denied"):
        msg = appdirs.data_dir_problem(root, _env(tmp_path))
    assert "read-only" in msg and "permissions" in msg and "delete portable.flag" not in msg


def test_full_disk_from_write_error(tmp_path):
    root = _app(tmp_path, portable=True)
    with patch.object(appdirs.tempfile, "NamedTemporaryFile", side_effect=OSError(errno.ENOSPC, "No space")):
        msg = appdirs.data_dir_problem(root, _env(tmp_path))
        assert appdirs.describe(root, _env(tmp_path))["writable"] is False
    assert "full" in msg


def test_permission_error_is_reported_not_raised(tmp_path):
    root = _app(tmp_path, portable=True)
    with patch.object(appdirs.tempfile, "NamedTemporaryFile", side_effect=PermissionError(errno.EACCES, "Denied")):
        msg = appdirs.data_dir_problem(root, _env(tmp_path))
    assert "not writable" in msg


def test_nearly_full_disk_reports_free_mb(tmp_path):
    root = _app(tmp_path, portable=True)
    with patch.object(appdirs, "_free_mb", return_value=7):
        msg = appdirs.data_dir_problem(root, _env(tmp_path))
    assert "Only 7 MB" in msg
    with patch.object(appdirs, "_free_mb", return_value=7):
        assert appdirs.data_dir_problem(root, _env(tmp_path), min_free_mb=5) is None


def test_unknown_free_space_is_not_a_problem(tmp_path):
    with patch.object(appdirs, "_free_mb", return_value=None):
        assert appdirs.data_dir_problem(_app(tmp_path, True), _env(tmp_path)) is None


def test_data_dir_that_is_a_file(tmp_path):
    root = _app(tmp_path, portable=True)
    (root / "LanTool-data").write_text("oops")
    msg = appdirs.data_dir_problem(root, _env(tmp_path))
    assert "is a file" in msg
    assert appdirs.describe(root, _env(tmp_path))["writable"] is False


def test_problem_check_never_raises(tmp_path):
    root = _app(tmp_path, portable=True)
    with patch.object(appdirs, "_inspect", side_effect=ValueError("bad path")):
        assert "bad path" in appdirs.data_dir_problem(root, _env(tmp_path))


# --- wipe targets / environment ---------------------------------------------------------------

def test_wipe_targets_portable_is_only_the_data_dir_with_spaces(tmp_path):
    root = _app(tmp_path, portable=True)
    got = appdirs.wipe_targets(root)
    assert got == {"portable": True, "data_dir": str(root / "LanTool-data"),
                   "items": ["vla-state", "vla-installed-by-lantool", "vla-adapter-state.json"]}


def test_wipe_targets_non_portable_has_no_data_dir(tmp_path):
    got = appdirs.wipe_targets(_app(tmp_path, portable=False))
    assert got["portable"] is False and got["data_dir"] is None


def test_wipe_environment_sets_portable_path_only_when_flagged(tmp_path):
    flagged = _app(tmp_path, portable=True)
    plain = _app(tmp_path, portable=False, name="Plain Copy")
    assert wipe.wipe_environment(flagged, {"A": "1"})[wipe.ENV_PORTABLE] == str(flagged / "LanTool-data")
    assert wipe.ENV_PORTABLE not in wipe.wipe_environment(plain, {"A": "1"})
    assert wipe.wipe_environment(plain, {"A": "1"})["A"] == "1"


def test_inherited_portable_variable_cannot_steer_the_wipe(tmp_path):
    plain = _app(tmp_path, portable=False)
    forged = {wipe.ENV_PORTABLE: str(tmp_path / "Documents")}
    assert wipe.ENV_PORTABLE not in wipe.wipe_environment(plain, forged)
    flagged = _app(tmp_path, portable=True, name="Flagged Copy")
    assert wipe.wipe_environment(flagged, forged)[wipe.ENV_PORTABLE] == str(flagged / "LanTool-data")


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows subprocess wrapper")
@pytest.mark.parametrize("portable", [True, False])
def test_wipe_windows_passes_environment_and_fixed_script(tmp_path, portable):
    root = _app(tmp_path, portable=portable)
    done = Mock(returncode=0, stdout='{"issues":[],"reboot":false}', stderr="")
    with patch.object(appdirs, "app_root", return_value=root), \
            patch.dict("os.environ", {wipe.ENV_PORTABLE: "C:\\Forged"}), \
            patch("silent_tunnel.wipe.subprocess.run", return_value=done) as run:
        assert wipe.wipe_windows() == {"report": {"issues": [], "reboot": False}}
    assert run.call_args.args[0][-1] == wipe.SCRIPT          # still one fixed script, no splicing
    env = run.call_args.kwargs["env"]
    if portable:
        assert env[wipe.ENV_PORTABLE] == str(root / "LanTool-data")
    else:
        assert wipe.ENV_PORTABLE not in env


# --- the PowerShell script text (no execution) ---------------------------------------------------

def test_script_reads_portable_path_from_env_not_from_text():
    assert "$env:" + wipe.ENV_PORTABLE in wipe.SCRIPT
    assert "portable.flag" in wipe.SCRIPT and "'LanTool-data'" in wipe.SCRIPT


def test_script_items_match_appdirs_for_portable_and_profiles():
    for item in appdirs.VLA_STATE_ITEMS:
        assert f"'{item}'" in wipe.SCRIPT                       # portable list
        assert f"'AppData\\Local\\LanTool\\{item}'" in wipe.SCRIPT   # profile list


def test_script_portable_branch_comes_before_and_skips_the_profile_walk():
    text = wipe.SCRIPT
    branch = text.index("if ($portableData)")
    walk = text.index("ProfileList")
    assert branch < walk
    assert re.search(r"if \(\$portableData\) \{.*?\breturn\b.*?\}\s*foreach \(\$ztProfile", text, re.S)


def test_script_keeps_safety_guards():
    assert "Unsafe removal path." in wipe.SCRIPT and "Linked path:" in wipe.SCRIPT


# --- store.data_dir() ------------------------------------------------------------------------------

def test_store_data_dir_portable_with_spaces_on_any_os(tmp_path, monkeypatch):
    root = _app(tmp_path, portable=True)
    monkeypatch.delenv("SILENT_TUNNEL_HOME", raising=False)
    monkeypatch.setattr(appdirs, "app_root", lambda: root)
    assert store.data_dir() == root / "LanTool-data" / "vla-state" / "standalone"


def test_store_data_dir_env_override_wins_over_portable(tmp_path, monkeypatch):
    root = _app(tmp_path, portable=True)
    monkeypatch.setattr(appdirs, "app_root", lambda: root)
    monkeypatch.setenv("SILENT_TUNNEL_HOME", str(tmp_path / "Tunnel Home"))
    assert store.data_dir() == tmp_path / "Tunnel Home"


@pytest.mark.skipif(__import__("os").name != "nt", reason="Windows default location")
def test_store_data_dir_non_portable_uses_localappdata(tmp_path, monkeypatch):
    root = _app(tmp_path, portable=False)
    monkeypatch.delenv("SILENT_TUNNEL_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local App Data"))
    monkeypatch.setattr(appdirs, "app_root", lambda: root)
    assert store.data_dir() == tmp_path / "Local App Data" / "LanTool" / "vla-state" / "standalone"
