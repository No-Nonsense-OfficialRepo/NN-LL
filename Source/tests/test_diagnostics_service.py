import json

from lantool.diagnostics import Check, CheckResult, WARN
from lantool.diagnostics.service import run_and_save, save_report, summarize, summarize_rows
from lantool.diagnostics.runner import run_checks


def _checks():
    def boom(report):
        raise RuntimeError("nope")
    return [Check("a", "Alpha", lambda r: {"x": 1}),
            Check("b", "Beta", lambda r: CheckResult("b", WARN, summary="slow")),
            Check("c", "Gamma", boom)]


def test_run_and_save_writes_json_and_summary(tmp_path):
    seen = []
    result = run_and_save(tmp_path, _checks(), progress=lambda t, i, n: seen.append((t, i, n)))
    data = json.loads(open(result["path"], encoding="utf-8").read())
    assert [c["name"] for c in data["checks"]] == ["a", "b", "c"]
    assert result["worst"] == "error"
    assert seen == [("Alpha", 1, 3), ("Beta", 2, 3), ("Gamma", 3, 3)]
    assert result["lines"][0] == "Alpha: ok"
    assert result["lines"][1] == "Beta: warn - slow"
    assert result["lines"][2] == "Gamma: error - nope"


def test_rows_are_structured_for_the_ui(tmp_path):
    result = run_and_save(tmp_path, _checks())
    base = {"fix": "", "fixLabel": "", "desc": ""}
    # worst first: error, warn, ok
    assert result["rows"] == [
        {"title": "Gamma", "status": "error", "detail": "nope", **base},
        {"title": "Beta", "status": "warn", "detail": "slow", **base},
        {"title": "Alpha", "status": "ok", "detail": "", **base},
    ]


def test_rows_fall_back_to_check_name():
    report = run_checks(_checks()[:1])
    assert summarize_rows(report) == [{"title": "a", "desc": "", "status": "ok", "detail": "", "fix": "", "fixLabel": ""}]


def test_save_report_keeps_only_newest(tmp_path):
    report = run_checks(_checks()[:1])
    for i in range(5):
        (tmp_path / f"connection-check-2020010{i}-000000.json").write_text("{}")
    path = save_report(report, tmp_path, keep=3)
    names = sorted(p.name for p in tmp_path.glob("connection-check-*.json"))
    assert len(names) == 3 and path.name in names


def test_summarize_falls_back_to_name():
    report = run_checks(_checks()[:1])
    assert summarize(report) == ["a: ok"]
