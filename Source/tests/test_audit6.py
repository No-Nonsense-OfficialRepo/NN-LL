import threading
from pathlib import Path

from lantool.filesync.index import HashCache


async def test_resume_uses_held_index_when_host_is_offline(tmp_path, monkeypatch):
    import lantool.filesync.client as client

    async def offline(*a, **k):
        raise ConnectionRefusedError("host offline")

    monkeypatch.setattr(client, "fetch_index", offline)
    held = {"files": []}
    res = await client._sync_game_once("127.0.0.1", 1, "pub", "game", tmp_path / "d", held_index=held)
    assert res.ok, res.error
    fresh = await client._sync_game_once("127.0.0.1", 1, "pub", "game", tmp_path / "d2", held_index={})
    assert not fresh.ok


def test_hashcache_saves_use_distinct_temp_files(tmp_path, monkeypatch):
    target = tmp_path / "cache.json"
    names = []
    import lantool.filesync.index as index
    real = index.replace_file

    def spy(src, dst):
        names.append(Path(src).name)
        real(src, dst)

    monkeypatch.setattr(index, "replace_file", spy)
    a, b = HashCache(target), HashCache(target)
    threads = [threading.Thread(target=c.save) for c in (a, b, a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(names) == 4 and len(set(names)) == 4
    assert target.exists() and not list(tmp_path.glob("*.tmp"))
