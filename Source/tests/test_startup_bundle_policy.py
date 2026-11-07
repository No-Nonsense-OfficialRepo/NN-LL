"""Startup trust: an imported bundle wins over the sidecar, and load failures are logged (audit A12)."""
import json
import logging
import os
import sys
from pathlib import Path
from unittest.mock import patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402
from lantool.trust import signing  # noqa: E402
from lantool.trust.bundle import create_bundle  # noqa: E402


def _bundle_file(folder, name):
    priv, pub = signing.generate_keypair()
    bundle = create_bundle(priv, pub, "a" * 16, "b" * 12, b"moon-bytes", "1")
    path = folder / name
    path.write_text(json.dumps(bundle), encoding="utf-8")
    return path, pub


def _app(config):
    app = object.__new__(core.LauncherCore)
    app.config_data = dict(config)
    app.client_bundle = None
    app.trusted_host_pub = config.get("trusted_host_pub")
    return app


def _load(app, auto, state):
    with patch.object(core, "APP_DIR", state), patch.object(core, "_write_config") as write_config:
        app._load_trusted_bundle(auto)
    return write_config


def test_imported_bundle_wins_over_the_sidecar(tmp_path):
    imported, imported_pub = _bundle_file(tmp_path, "imported.json")
    sidecar, _sidecar_pub = _bundle_file(tmp_path, "sidecar.json")
    app = _app({"trusted_host_pub": imported_pub, "trusted_bundle_path": str(imported)})
    write_config = _load(app, sidecar, tmp_path / "state")
    assert app.trusted_host_pub == imported_pub
    assert app.client_bundle["host_pub"] == imported_pub
    assert app.config_data["trusted_bundle_path"] == str(imported)
    write_config.assert_not_called()


def test_sidecar_seeds_trust_when_nothing_was_imported(tmp_path):
    sidecar, sidecar_pub = _bundle_file(tmp_path, "sidecar.json")
    app = _app({})
    state = tmp_path / "state"
    _load(app, sidecar, state)
    assert app.trusted_host_pub == sidecar_pub
    assert app.config_data["trusted_bundle_path"] == str(state / "trusted_host_bundle.json")
    assert (state / "trusted_host_bundle.json").is_file()


def test_unreadable_imported_bundle_is_logged_and_the_sidecar_is_used(tmp_path, caplog):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json", encoding="utf-8")
    sidecar, sidecar_pub = _bundle_file(tmp_path, "sidecar.json")
    app = _app({"trusted_host_pub": "old", "trusted_bundle_path": str(broken)})
    caplog.set_level(logging.ERROR)
    _load(app, sidecar, tmp_path / "state")
    assert "imported join bundle" in caplog.text
    assert app.trusted_host_pub == sidecar_pub


def test_explicit_lan_switch_is_kept_when_old_sidecar_exists(tmp_path):
    sidecar, _ = _bundle_file(tmp_path, "sidecar.json")
    app = _app({"trusted_host_pub": "new-host"})
    write_config = _load(app, sidecar, tmp_path / "state")
    assert app.trusted_host_pub == "new-host"
    assert app.client_bundle is None
    write_config.assert_not_called()


def test_unreadable_sidecar_is_logged_not_swallowed(tmp_path, caplog):
    broken = tmp_path / "sidecar.json"
    broken.write_text("{not json", encoding="utf-8")
    app = _app({})
    caplog.set_level(logging.ERROR)
    write_config = _load(app, broken, tmp_path / "state")
    assert "bundled join bundle" in caplog.text
    assert app.client_bundle is None
    assert app.trusted_host_pub is None
    write_config.assert_not_called()
