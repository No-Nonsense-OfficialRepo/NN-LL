"""Phase 4 finish: join-timing summary and throttled auto-diagnose after a staged join failure."""
from types import SimpleNamespace

from lantool.diagnostics import checks
from lantool.diagnostics.model import Report, OK
from lantool.qt import bridge as bridge_mod

B = bridge_mod.LauncherBridge

LINES = [
    "2026-11-01T10:00:00.000+00:00 pid=1 event=room_key.join duration_s=2.500 outcome=connected",
    "2026-11-01T10:05:00.000+00:00 pid=1 event=room_key.join duration_s=61.000 outcome=vla_approval:RuntimeError stage=vla_join code=vla_not_connected",
    "garbage line",
]


def test_summarize_join_timings_counts_slowest_and_last_failure():
    text = checks.summarize_join_timings(LINES)
    assert "2 timed events, 1 not connected" in text
    assert "slowest room_key.join 61.0s" in text
    assert "last failure room_key.join" in text


def test_summarize_join_timings_empty():
    assert checks.summarize_join_timings([]) == "No timed joins recorded"
    assert checks.summarize_join_timings(["nothing useful"]) == "No timed joins recorded"


def test_recent_join_timing_reads_log(tmp_path, monkeypatch):
    log = tmp_path / "t.log"
    log.write_text("\n".join(LINES), encoding="utf-8")
    monkeypatch.setattr(checks, "join_timing_log", lambda: log)
    r = checks.recent_join_timing(Report("u", "c"))
    assert r.status == OK and "2 timed events" in r.summary and len(r.data) == 3


def test_recent_join_timing_missing_log(tmp_path, monkeypatch):
    monkeypatch.setattr(checks, "join_timing_log", lambda: tmp_path / "none.log")
    r = checks.recent_join_timing(Report("u", "c"))
    assert r.status == OK and "No join timings" in r.summary


def _me(**kw):
    started = []
    me = SimpleNamespace(_preview=False, _diag={}, started=started, _start_diag=lambda m: started.append(m))
    me.__dict__.update(kw)
    return me


def test_auto_diagnose_runs_once_for_staged_error_then_throttles():
    me = _me()
    B._maybe_auto_diagnose(me, "showerror", "vla_join")
    B._maybe_auto_diagnose(me, "showerror", "vla_join")
    assert me.started == [None]


def test_auto_diagnose_skips_info_unstaged_preview_and_running():
    for kind, stage, extra in (("showinfo", "x", {}), ("showerror", "", {}),
                               ("showerror", "x", {"_preview": True}),
                               ("showerror", "x", {"_diag": {"running": True}})):
        me = _me(**extra)
        B._maybe_auto_diagnose(me, kind, stage)
        assert me.started == []
