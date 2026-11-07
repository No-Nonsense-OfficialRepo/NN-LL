"""Two avatar saves in the same second must both succeed and keep the newest one (audit A04).

Filenames used to be built from whole seconds, so the second save overwrote the
first and then deleted the file it had just written.
"""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402


def _fake_launcher():
    fake = object.__new__(core.LauncherCore)
    fake.config_data = {}
    fake.presence_client = None
    return fake


def test_two_avatar_saves_in_the_same_second_keep_the_second(tmp_path):
    first_src = tmp_path / "first.png"
    first_src.write_bytes(b"first")
    second_src = tmp_path / "second.png"
    second_src.write_bytes(b"second")
    app_dir = tmp_path / "app"
    fake = _fake_launcher()

    with patch.object(core, "APP_DIR", app_dir), patch.object(core, "_write_config"), \
         patch("time.time", return_value=1000.0):
        fake.save_avatar(str(first_src))
        first = Path(fake.config_data["avatar"])
        fake.save_avatar(str(second_src))
        second = Path(fake.config_data["avatar"])

    assert first != second
    assert second.is_file()
    assert second.read_bytes() == b"second"
    assert not first.exists()  # the replaced avatar is removed, not the new one
