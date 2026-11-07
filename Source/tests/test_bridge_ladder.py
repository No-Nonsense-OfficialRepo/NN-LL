"""LauncherBridge.runLadder / _start_diag, called unbound with a fake self (no Qt app)."""
from types import SimpleNamespace

from lantool.qt import bridge as bridge_mod

B = bridge_mod.LauncherBridge


def fake(**kw):
    started = []
    ns = SimpleNamespace(_preview=False, _wiping=False, _closing=False, _diag={}, publish=lambda: None,
                         after=lambda *a: None, started=started,
                         trusted_host_pub="PUB", **kw)
    ns._start_diag = lambda make: started.append(make)
    return ns


def test_empty_address_sets_error_and_does_not_start():
    me = fake()
    B.runLadder(me, "   ")
    assert me.started == []
    assert "IP" in me._diag["error"]


def test_address_starts_with_pinned_key(monkeypatch):
    me = fake()
    seen = {}
    import lantool.diagnostics.ladder as ladder
    monkeypatch.setattr(ladder, "client_ladder_checks",
                        lambda addr, trusted_pub=None: seen.update(a=addr, p=trusted_pub) or ["c"])
    B.runLadder(me, " 10.0.0.5 ")
    assert len(me.started) == 1
    assert me.started[0]() == ["c"]
    assert seen == {"a": "10.0.0.5", "p": "PUB"}


def test_start_diag_ignored_while_running_or_preview():
    for state in ({"running": True}, None):
        me = SimpleNamespace(_preview=state is None, _wiping=False, _closing=False, _diag=state or {}, publish=lambda: None)
        before = dict(me._diag)
        B._start_diag(me, None)
        assert me._diag == before


def test_diagnose_from_dialog_closes_popup_and_opens_diagnostics():
    pages = []
    me = fake(_dialog={"title": "Couldn't join", "stage": "beacon"}, _setting_tab="Network")
    me.show_page = pages.append
    B.diagnoseFromDialog(me)
    assert me._dialog == {}
    assert me._setting_tab == "Diagnostics"
    assert pages == ["settings"]
    assert me.started == [None]


def test_run_host_check_starts_host_checks(monkeypatch):
    me = fake()
    import lantool.diagnostics.host_checks as hc
    monkeypatch.setattr(hc, 'host_checks', lambda: ['h'])
    B.runHostCheck(me)
    assert len(me.started) == 1 and me.started[0]() == ['h']
