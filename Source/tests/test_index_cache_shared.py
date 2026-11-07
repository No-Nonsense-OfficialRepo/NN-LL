"""The host shares one hash cache across games. Indexing one game must not drop another game's hashes."""
from pathlib import Path

from lantool.filesync.index import HashCache, build_index


def _game(root: Path, name: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(b"x" * 1000)
    return root


def test_indexing_one_game_keeps_other_games_hashes(tmp_path):
    a = _game(tmp_path / "GameA", "a.dat")
    b = _game(tmp_path / "GameB", "b.dat")
    cache = HashCache()
    build_index("A", a, cache)
    assert str(a / "a.dat") in cache._d
    build_index("B", b, cache)
    assert str(a / "a.dat") in cache._d, "indexing B must not forget A's hashes"
    assert str(b / "b.dat") in cache._d


def test_stale_entries_under_the_same_game_are_still_dropped(tmp_path):
    a = _game(tmp_path / "GameA", "a.dat")
    cache = HashCache()
    build_index("A", a, cache)
    cache._d[str(a / "gone.dat")] = [1, 1, "0" * 64]
    build_index("A", a, cache)
    assert str(a / "gone.dat") not in cache._d
    assert str(a / "a.dat") in cache._d


def test_prefix_of_another_folder_is_not_treated_as_inside(tmp_path):
    a = _game(tmp_path / "Game", "a.dat")
    sibling = str(tmp_path / "Game2" / "x.dat")
    cache = HashCache()
    cache._d[sibling] = [1, 1, "0" * 64]
    build_index("A", a, cache)
    assert sibling in cache._d
