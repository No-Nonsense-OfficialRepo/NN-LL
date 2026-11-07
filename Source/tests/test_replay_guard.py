"""Replay protection: a validly signed but stale index or game list must not be accepted after a newer one."""
import pytest
from lantool.trust.freshness import FreshnessGuard, StaleError
from lantool.trust.signing import generate_keypair
from lantool.filesync.server import FileSyncServer
from lantool.filesync.client import fetch_index


def test_guard_accepts_equal_or_newer_and_rejects_older():
    guard = FreshnessGuard()
    guard.check("host", "index/g", {"issued": 100})
    guard.check("host", "index/g", {"issued": 100})   # the same data fetched again
    guard.check("host", "index/g", {"issued": 101})
    with pytest.raises(StaleError):
        guard.check("host", "index/g", {"issued": 100})


def test_guard_keeps_each_signer_and_kind_separate():
    guard = FreshnessGuard()
    guard.check("host-a", "index/g", {"issued": 500})
    guard.check("host-b", "index/g", {"issued": 1})
    guard.check("host-a", "index/other", {"issued": 1})
    guard.check("host-a", "library", {"issued": 1})


def test_unstamped_data_is_accepted_only_until_a_stamped_one_was_seen():
    guard = FreshnessGuard()
    guard.check("old-host", "library", {})            # an older Host version never stamps
    guard.check("old-host", "library", {})
    guard.check("host", "library", {"issued": 5})
    with pytest.raises(StaleError):                    # downgrade by replaying pre-stamp data
        guard.check("host", "library", {})


@pytest.mark.parametrize("bad", [-1, 1.5, "7", True, [1], {}])
def test_guard_rejects_malformed_stamps(bad):
    with pytest.raises(StaleError):
        FreshnessGuard().check("host", "library", {"issued": bad})


async def make_host(tmp_path):
    priv, pub = generate_keypair()
    game = tmp_path / "lib" / "bfbc2"
    game.mkdir(parents=True)
    (game / "game.exe").write_bytes(b"MZ" + b"x" * 500)
    srv = FileSyncServer(priv, tmp_path / "lib", host="127.0.0.1", port=0)
    await srv.start()
    return srv, pub


async def test_host_stamps_strictly_increase_even_if_the_clock_steps_back(tmp_path, monkeypatch):
    srv, pub = await make_host(tmp_path)
    try:
        first = (await srv.signed_index("bfbc2"))["issued"]
        monkeypatch.setattr("lantool.filesync.server.time.time", lambda: 1.0)  # clock jumps back to 1970
        second = (await srv.signed_index("bfbc2"))["issued"]
        third = (await srv.signed_index("bfbc2"))["issued"]
        assert first < second < third
    finally:
        await srv.stop()


async def test_replayed_old_index_is_rejected_after_a_newer_one(tmp_path):
    srv, pub = await make_host(tmp_path)
    try:
        old = await srv.signed_index("bfbc2")
        assert len(await fetch_index("127.0.0.1", srv.port, pub, "bfbc2")) == 1   # live, newer stamp

        async def replay(game_id):
            return old
        srv.signed_index = replay
        with pytest.raises(Exception, match="older"):
            await fetch_index("127.0.0.1", srv.port, pub, "bfbc2")
    finally:
        await srv.stop()
