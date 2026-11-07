"""The host key is never silently replaced, and replacement is backed up and atomic (audit A13)."""
import json
import logging
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402
from lantool.trust import signing  # noqa: E402


def _identity(state):
    with patch.object(core, "APP_DIR", state):
        return core.LauncherCore._host_identity(SimpleNamespace())


def _backups(state):
    return sorted(state.glob("host_identity.json.invalid-*"))


def test_valid_identity_is_returned_unchanged(tmp_path):
    private, public = signing.generate_keypair()
    path = tmp_path / "host_identity.json"
    path.write_text(json.dumps({"private": private, "public": public}), encoding="utf-8")
    assert _identity(tmp_path) == (private, public)
    assert _backups(tmp_path) == []


def test_missing_identity_is_created_without_a_backup(tmp_path):
    state = tmp_path / "state"
    private, public = _identity(state)
    stored = json.loads((state / "host_identity.json").read_text(encoding="utf-8"))
    assert (stored["private"], stored["public"]) == (private, public)
    assert _backups(state) == []
    assert not (state / "host_identity.json.tmp").exists()


def test_corrupt_identity_is_backed_up_then_replaced_atomically(tmp_path, caplog):
    path = tmp_path / "host_identity.json"
    path.write_bytes(b"{truncated")
    caplog.set_level(logging.ERROR)
    private, public = _identity(tmp_path)
    backups = _backups(tmp_path)
    assert len(backups) == 1 and backups[0].read_bytes() == b"{truncated"
    stored = json.loads(path.read_text(encoding="utf-8"))
    assert (stored["private"], stored["public"]) == (private, public)
    assert not (tmp_path / "host_identity.json.tmp").exists()
    assert "backed up" in caplog.text


def test_mismatched_keypair_is_backed_up_then_replaced(tmp_path):
    private, _public = signing.generate_keypair()
    _other_private, other_public = signing.generate_keypair()
    path = tmp_path / "host_identity.json"
    original = json.dumps({"private": private, "public": other_public})
    path.write_text(original, encoding="utf-8")
    new_private, new_public = _identity(tmp_path)
    assert (new_private, new_public) != (private, other_public)
    assert _backups(tmp_path)[0].read_text(encoding="utf-8") == original


def test_transient_read_failure_does_not_regenerate_the_key(tmp_path):
    private, public = signing.generate_keypair()
    path = tmp_path / "host_identity.json"
    original = json.dumps({"private": private, "public": public})
    path.write_text(original, encoding="utf-8")
    with patch.object(core.Path, "read_bytes", side_effect=PermissionError("locked")):
        with pytest.raises(RuntimeError, match="left unchanged"):
            _identity(tmp_path)
    assert path.read_text(encoding="utf-8") == original
    assert _backups(tmp_path) == []


def test_failed_backup_stops_before_the_old_key_is_replaced(tmp_path):
    path = tmp_path / "host_identity.json"
    path.write_bytes(b"{truncated")
    with patch.object(core.Path, "write_bytes", side_effect=OSError("disk full")):
        with pytest.raises(RuntimeError, match="could not be backed up"):
            _identity(tmp_path)
    assert path.read_bytes() == b"{truncated"
