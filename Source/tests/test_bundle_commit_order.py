"""Bundle trust is committed last and atomically; imports are refused mid-room (audits A10 and A11)."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import json  # noqa: E402

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402
from lantool.trust import signing  # noqa: E402
from lantool.trust.bundle import create_bundle, load_bundle  # noqa: E402


def _bundle_file(tmp_path):
    priv, pub = signing.generate_keypair()
    bundle = create_bundle(priv, pub, "a" * 16, "b" * 12, b"moon-bytes", "1")
    path = tmp_path / "host.json"
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path, pub


def _app(tmp_path, trusted="old-key"):
    app = object.__new__(core.LauncherCore)
    app.config_data = {"trusted_host_pub": trusted} if trusted else {}
    app.game_root = tmp_path / "games"
    app.game_root.mkdir()
    app.room = None
    app.room_controller = None
    app.busy = False
    app.syncing_game = None
    app.client_bundle = None
    app.trusted_host_pub = trusted
    app.pages = {"room": MagicMock()}
    app.after = MagicMock()
    return app


@pytest.fixture
def env(tmp_path):
    state = tmp_path / "state"
    with patch.object(core, "APP_DIR", state), \
         patch.object(core, "_write_config") as write_config, \
         patch.object(core, "messagebox") as box:
        yield SimpleNamespace(state=state, write_config=write_config, box=box)


def test_invalid_folder_leaves_trust_and_setup_untouched(tmp_path, env):
    path, _pub = _bundle_file(tmp_path)
    blocker = tmp_path / "file.txt"
    blocker.write_text("not a folder")
    app = _app(tmp_path, trusted=None)
    with pytest.raises(OSError):
        app.complete_setup("Ann", str(blocker / "games"), False, str(path))
    assert app.trusted_host_pub is None
    assert "trusted_host_pub" not in app.config_data
    assert not app.config_data.get("setup_completed")
    assert not (env.state / "trusted_host_bundle.json").exists()


def test_empty_folder_leaves_trust_untouched(tmp_path, env):
    path, _pub = _bundle_file(tmp_path)
    app = _app(tmp_path, trusted=None)
    with pytest.raises(ValueError):
        app.complete_setup("Ann", "  ", False, str(path))
    assert app.trusted_host_pub is None
    assert not app.config_data.get("setup_completed")


def test_failed_bundle_write_keeps_the_old_trust(tmp_path, env):
    path, _pub = _bundle_file(tmp_path)
    blocker = tmp_path / "blocked"
    blocker.write_text("not a folder")
    app = _app(tmp_path)
    with patch.object(core, "APP_DIR", blocker / "state"):
        assert app.import_bundle(str(path), start_discovery=False) is False
    assert app.trusted_host_pub == "old-key"
    assert app.config_data["trusted_host_pub"] == "old-key"
    assert app.client_bundle is None
    env.box.showerror.assert_called_once()


def test_import_during_a_room_is_refused(tmp_path, env):
    path, _pub = _bundle_file(tmp_path)
    app = _app(tmp_path)
    app.room = SimpleNamespace(code="ROOM")
    assert app.import_bundle(str(path), start_discovery=False) is False
    assert app.trusted_host_pub == "old-key"
    env.box.showinfo.assert_called_once()
    assert not (env.state / "trusted_host_bundle.json").exists()


def test_import_stores_the_verified_bundle_and_trusts_the_host(tmp_path, env):
    path, pub = _bundle_file(tmp_path)
    app = _app(tmp_path, trusted=None)
    assert app.import_bundle(str(path), start_discovery=False) is True
    assert app.trusted_host_pub == pub
    stored, _moon = load_bundle(env.state / "trusted_host_bundle.json")
    assert stored["host_pub"] == pub
    assert app.config_data["trusted_bundle_path"] == str(env.state / "trusted_host_bundle.json")
