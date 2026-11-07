import time
import threading

from lantool.diagnostics import Check, CheckResult, run_checks, redact, redact_text, OK, WARN, ERROR


def test_one_failing_check_does_not_stop_the_report():
    def boom(_):
        raise RuntimeError("nope")
    rep = run_checks([Check("a", "A", lambda r: {"x": 1}), Check("b", "B", boom),
                      Check("c", "C", lambda r: {"y": 2})])
    assert [r.status for r in rep.results] == [OK, ERROR, OK]
    assert rep.get("b").error == "nope"
    assert rep.worst == ERROR


def test_hung_check_times_out_and_next_still_runs():
    rep = run_checks([Check("slow", "Slow", lambda r: time.sleep(2), timeout_s=0.1),
                      Check("after", "After", lambda r: 1)])
    assert rep.get("slow").status == ERROR and "Timed out" in rep.get("slow").error
    assert rep.get("after").status == OK


def test_check_can_return_own_result_and_see_earlier_results():
    rep = run_checks([Check("first", "F", lambda r: 5),
                      Check("second", "S", lambda r: CheckResult("x", WARN, r.get("first").data))])
    assert rep.get("second").status == WARN and rep.get("second").data == 5


def test_progress_reports_each_check():
    seen = []
    run_checks([Check("a", "A", lambda r: 1), Check("b", "B", lambda r: 1)],
               progress=lambda t, i, n: seen.append((t, i, n)))
    assert seen == [("A", 1, 2), ("B", 2, 2)]


def test_timed_out_check_is_not_restarted_or_allowed_to_mutate_report():
    release, finished = threading.Event(), threading.Event()
    calls = []
    def stuck(snapshot):
        calls.append(1)
        release.wait(5)
        snapshot.get('prior').data['value'] = 'late'
        snapshot.results.clear()
        finished.set()
    check = Check('stuck-isolated', 'Stuck', stuck, timeout_s=0.01)
    try:
        report = run_checks([Check('prior', 'Prior', lambda r: {'value': 'original'}), check])
        repeated = run_checks([check])
        assert 'still running' in repeated.get(check.name).error
        assert calls == [1]
        release.set()
        assert finished.wait(2)
        assert report.get('prior').data == {'value': 'original'}
        assert report.get(check.name).status == ERROR
    finally:
        release.set()


def test_stuck_workers_are_bounded_and_release_capacity(monkeypatch):
    from lantool.diagnostics import runner
    # The existing timeout test may still own a worker; allow exactly one more.
    with runner._workers_lock:
        limit = len(runner._active_checks) + 1
    monkeypatch.setattr(runner, 'MAX_DIAGNOSTIC_WORKERS', limit)
    release, finished = threading.Event(), threading.Event()
    def stuck(_):
        release.wait(5)
        finished.set()
    check = Check('bounded-stuck', 'Stuck', stuck, timeout_s=0.01)
    try:
        run_checks([check])
        report = run_checks([Check('blocked-capacity', 'Blocked', lambda r: 1)])
        assert 'worker limit' in report.get('blocked-capacity').error
    finally:
        release.set()
        assert finished.wait(2)
    # Synchronize with the worker's finally block before checking capacity.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with runner._workers_lock:
            if check.name not in runner._active_checks:
                break
        time.sleep(0.001)
    assert run_checks([Check('capacity-restored', 'Restored', lambda r: 1)]).get('capacity-restored').status == OK


def test_redact_removes_secrets_and_user_names():
    out = redact({"authtoken": "abc", "ok": "fine", "nested": [{"Secret": "x"}],
                  "log": "X-ZT1-Auth: deadbeef failed at C:\\Users\\Alice\\AppData"})
    assert out["authtoken"] == "[redacted]" and out["nested"][0]["Secret"] == "[redacted]"
    assert "deadbeef" not in out["log"] and "Alice" not in out["log"]
    assert out["ok"] == "fine"


def test_redact_text_identity_secret():
    s = "id " + "a1b2c3d4e5:0:" + "A" * 60
    assert "AAAA" not in redact_text(s)


def test_redact_profile_with_spaces_and_forward_slashes():
    for path in (r'C:\Users\Test User\AppData\Local', 'C:/Users/Test User/AppData/Local',
                 "C:/Users/Test O'Connor/AppData/Local"):
        result = redact_text('Failed at ' + path)
        assert 'Test' not in result and 'User/' not in result
        assert 'Connor' not in result
        assert '<user>' in result and 'AppData' in result
