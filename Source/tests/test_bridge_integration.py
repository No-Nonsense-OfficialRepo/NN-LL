"""WP-G bridge wiring: cleanup, join pack, startup dialog. Fakes only; no dialogs, no elevation."""
from types import SimpleNamespace
from importlib import import_module
import pytest


@pytest.fixture(autouse=True)
def _cleanup_dialogs_follow_bridge(monkeypatch):
    """cleanup_ui moved the dialog calls out of bridge.py; keep patches on bridge_mod effective."""
    cleanup_ui = import_module(bridge_mod.__package__ + ".cleanup_ui")
    monkeypatch.setattr(cleanup_ui.core, '_other_launcher_running', lambda role: False)

    class _Dialogs:
        def __getattr__(self, name):
            return getattr(bridge_mod.QMessageBox, name)
    monkeypatch.setattr(cleanup_ui, "QMessageBox", _Dialogs())

import pytest

bridge_mod = pytest.importorskip("lantool.qt.bridge")
B = bridge_mod.LauncherBridge


def _fake_qmb(answer=None):
    calls = []
    SB = SimpleNamespace(Yes=1, Cancel=2, No=3)

    class Q:
        StandardButton = SB

        @staticmethod
        def question(*a, **k):
            calls.append(("question", a))
            return answer

        @staticmethod
        def warning(*a, **k):
            calls.append(("warning", a))

        @staticmethod
        def information(*a, **k):
            calls.append(("information", a))

    return Q, calls


def _fake_self(**over):
    base = SimpleNamespace(_preview=False, busy=False, room=None, _beacon_joining=False)
    for k, v in over.items():
        setattr(base, k, v)
    return base


def _cleanup_fake(**over):
    """Fake bridge for the in-launcher cleanup confirmation (no native dialogs)."""
    log = SimpleNamespace(published=0, messages=[])

    def publish():
        log.published += 1

    def ui_message(kind, title, message, *a, **k):
        log.messages.append((kind, title, message))

    fake = _fake_self(_cleanup_confirm=None, publish=publish, ui_message=ui_message,
                      after=lambda ms, cb, *a: cb(*a), **over)
    return fake, log


def test_cleanup_is_noop_in_preview(monkeypatch):
    Q, calls = _fake_qmb()
    monkeypatch.setattr(bridge_mod, "QMessageBox", Q)
    import silent_tunnel.cleanup as cleanup
    monkeypatch.setattr(cleanup, "plan", lambda: pytest.fail("plan must not run in preview"))
    fake, log = _cleanup_fake(_preview=True)
    B.cleanupPC(fake)
    assert calls == [] and fake._cleanup_confirm is None and log.published == 0


def test_cleanup_shows_plan_in_launcher_and_cancel_never_runs_elevated(monkeypatch):
    Q, calls = _fake_qmb()
    monkeypatch.setattr(bridge_mod, "QMessageBox", Q)
    import silent_tunnel.cleanup as cleanup
    monkeypatch.setattr(cleanup, "plan", lambda: ["Would remove: rule x"])
    monkeypatch.setattr(cleanup, "run", lambda: pytest.fail("run must not run after Cancel"))
    fake, log = _cleanup_fake()
    B.cleanupPC(fake)
    assert fake._cleanup_confirm == {"lines": ["Would remove: rule x"]}
    assert log.published == 1 and calls == []  # themed popup, no native dialog
    B.cancelCleanup(fake)
    assert fake._cleanup_confirm is None and log.published == 2
    B.confirmCleanup(fake)  # nothing pending: must not run anything
    assert log.messages == []


def test_cleanup_confirm_runs_once_and_reports(monkeypatch):
    import silent_tunnel.cleanup as cleanup
    monkeypatch.setattr(cleanup, "plan", lambda: ["Would remove: rule x"])
    runs = []
    monkeypatch.setattr(cleanup, "run", lambda: runs.append(1) or {"removed": ["rule x"], "left": []})

    class Inline:
        def __init__(self, target, **kw): self.target = target
        def start(self): self.target()
    monkeypatch.setattr(bridge_mod.threading, "Thread", Inline)
    fake, log = _cleanup_fake()
    fake._cleanup_done = lambda r, e: B._cleanup_done(fake, r, e)
    B.cleanupPC(fake)
    B.confirmCleanup(fake)
    assert runs == [1] and fake._cleanup_confirm is None
    assert log.messages and log.messages[-1][0] == "showinfo" and "rule x" in log.messages[-1][2]


def test_cleanup_confirmation_revalidates_room(monkeypatch):
    import silent_tunnel.cleanup as cleanup
    monkeypatch.setattr(cleanup, 'run', lambda: pytest.fail('active room must be kept'))
    fake, log = _cleanup_fake(room=object())
    fake._cleanup_confirm = {'lines': []}
    B.confirmCleanup(fake)
    assert fake._cleanup_confirm is None and not fake.busy
    assert log.messages[-1][1] == 'Cleanup cancelled'


def test_cleanup_holds_busy_until_worker_completion(monkeypatch):
    pending = []
    class Held:
        def __init__(self, target, **kw): pending.append(target)
        def start(self): pass
    monkeypatch.setattr(bridge_mod.threading, 'Thread', Held)
    fake, log = _cleanup_fake()
    fake._cleanup_confirm = {'lines': []}
    B.confirmCleanup(fake)
    assert fake.busy and len(pending) == 1
    B._cleanup_done(fake, None, 'failed')
    assert not fake.busy


def test_cleanup_done_lists_removed_and_left():
    fake, log = _cleanup_fake()
    B._cleanup_done(fake, {"removed": ["rule A"], "left": ["ZeroTier kept"]}, "")
    kind, title, text = log.messages[0]
    assert kind == "showinfo"
    assert "rule A" in text and "ZeroTier kept" in text


def test_cleanup_done_reports_error():
    fake, log = _cleanup_fake()
    B._cleanup_done(fake, None, "boom")
    assert log.messages and log.messages[0][0] == "showerror" and "boom" in log.messages[0][2]


def test_save_join_pack_is_noop_without_room(monkeypatch):
    Q, calls = _fake_qmb()
    monkeypatch.setattr(bridge_mod, "QMessageBox", Q)
    B.saveJoinPack(_fake_self(room=None))
    B.saveJoinPack(_fake_self(_preview=True, room=object()))
    assert calls == []


def test_startup_dialog_silent_when_no_problems(monkeypatch):
    import lantool.startup_checks as sc
    monkeypatch.setattr(sc, "run", lambda *a, **k: [])
    fake = _fake_self()
    B._show_startup_problems(fake)
    assert not hasattr(fake, "_startup_box")


def test_startup_advisories_are_silent_but_actual_errors_show(monkeypatch):
    from unittest.mock import Mock
    import lantool.startup_checks as sc
    advisory = sc.Problem('downloaded', sc.WARN, 'Windows download mark', 'Unblock files')
    error = sc.Problem('missing', sc.ERROR, 'A required file is missing', 'Restore the file')
    box = Mock()
    monkeypatch.setattr(bridge_mod, 'QMessageBox', box)
    monkeypatch.setattr(sc, 'run', lambda *a, **k: [advisory])
    fake = _fake_self()
    B._show_startup_problems(fake)
    box.assert_not_called()
    monkeypatch.setattr(sc, 'run', lambda *a, **k: [advisory, error])
    B._show_startup_problems(fake)
    box.assert_called_once()
    assert 'A required file is missing' in box.call_args.args[2]
    assert 'Windows download mark' not in box.call_args.args[2]
    box.return_value.open.assert_called_once()
