"""Clean up this PC: dry-run plan, ZeroTier safety, nothing-to-clean. All mocked; no admin, no firewall."""
from silent_tunnel import cleanup

OUR = "GamerUtility-0123456789abcdef-TCP"
OUR_UDP = "GamerUtility-0123456789abcdef-UDP"


def _rules(*names):
    return [{"name": n, "program": "x.exe", "enabled": True, "direction": "Inbound", "action": "Allow"}
            for n in names]


def _patch(monkeypatch, *, zt=False, registered=False, owned=False, record=None):
    monkeypatch.setattr(cleanup, "_zerotier_service_present", lambda: zt)
    monkeypatch.setattr(cleanup, "_vla_registered", lambda: registered)
    monkeypatch.setattr(cleanup, "_vla_owned", lambda: owned)
    monkeypatch.setattr(cleanup, "_private_record", lambda: record)


def test_plan_lists_our_rules_and_vla_as_removals(monkeypatch):
    _patch(monkeypatch, registered=True, owned=True)
    lines = cleanup.plan(_rules(OUR, OUR_UDP, "Some Other Rule"))
    assert lines[0] == "Would remove:"
    assert f"  - Remove firewall rule {OUR}" in lines
    assert f"  - Remove firewall rule {OUR_UDP}" in lines
    assert not any("Some Other Rule" in l for l in lines)
    assert any("LanLauncherVLA" in l for l in lines)
    assert "Would leave:" in lines
    assert any("shared ZeroTier driver" in l for l in lines)


def test_plan_is_a_dry_run_and_calls_nothing_elevated(monkeypatch):
    _patch(monkeypatch, registered=True, owned=True)

    def boom(*a, **k):
        raise AssertionError("elevation must not run in plan()")
    monkeypatch.setattr(cleanup, "run_elevated", boom)
    cleanup.plan(_rules(OUR))


def test_ordinary_zerotier_is_left_alone(monkeypatch):
    _patch(monkeypatch, zt=True, registered=True, owned=False)
    lines = cleanup.plan(_rules())
    assert any(l.endswith("ZeroTier (ordinary install): left alone") for l in lines)
    assert any("registered but not installed by this launcher; left alone" in l for l in lines)
    assert not any("LanLauncherVLA" in l for l in lines[: lines.index("Would leave:")])


def test_run_never_removes_zerotier_service(monkeypatch):
    _patch(monkeypatch, zt=True, registered=True, owned=False)
    calls = []

    def fake(action, **kw):
        calls.append((action, kw))
        return {"removed": ["firewall rule " + OUR]}
    result = cleanup.run(_rules(OUR), elevate=fake)
    assert calls == [("cleanup_pc", {"remove_service": False, "remove_private": False})]
    assert result["ran"] is True
    assert any(l.endswith("ZeroTier (ordinary install): left alone") for l in result["left"])


def test_run_with_nothing_to_clean_does_not_elevate(monkeypatch):
    _patch(monkeypatch)

    def boom(*a, **k):
        raise AssertionError("no elevation when nothing to clean")
    result = cleanup.run([], elevate=boom)
    assert result["ran"] is False
    assert result["removed"] == []
    assert any(l.endswith("Firewall rules: none of ours found") for l in cleanup.plan([]))


def test_private_change_removed_only_when_recorded(monkeypatch):
    _patch(monkeypatch, record=None)
    assert not any("Public" in l for l in cleanup.plan([]) if l.startswith("  - Set"))
    _patch(monkeypatch, record={"changed": True, "indexes": [7]})
    assert any("Set the network profile back to Public" in l for l in cleanup.plan([]))


def test_unreadable_rules_are_reported_not_guessed(monkeypatch):
    _patch(monkeypatch)
    monkeypatch.setattr(cleanup.firewall, "list_our_rules", lambda: None)
    lines = cleanup.plan()
    assert any("could not be read" in l for l in lines)
