import json
from lantool.trust.freshness import FreshnessGuard, StaleError
import pytest


def test_stamps_survive_restart(tmp_path):
    path = tmp_path / "freshness.json"
    first = FreshnessGuard()
    first.bind(path, "pubA")
    first.check("pubA", "index/g1", {"issued": 5})

    second = FreshnessGuard()
    second.bind(path, "pubA")
    with pytest.raises(StaleError):
        second.check("pubA", "index/g1", {"issued": 4})
    second.check("pubA", "index/g1", {"issued": 5})


def test_changed_host_key_starts_fresh(tmp_path):
    path = tmp_path / "freshness.json"
    first = FreshnessGuard()
    first.bind(path, "pubA")
    first.check("pubA", "library", {"issued": 9})

    second = FreshnessGuard()
    second.bind(path, "pubB")
    second.check("pubB", "library", {"issued": 1})


def test_other_keys_are_dropped_from_file(tmp_path):
    path = tmp_path / "freshness.json"
    guard = FreshnessGuard()
    guard.bind(path, "pubA")
    guard.check("pubA", "library", {"issued": 3})
    guard.bind(path, "pubB")
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert "pubA" not in saved["signers"]


def test_unbound_guard_writes_nothing(tmp_path):
    guard = FreshnessGuard()
    guard.check("pubA", "library", {"issued": 2})
    assert list(tmp_path.iterdir()) == []
