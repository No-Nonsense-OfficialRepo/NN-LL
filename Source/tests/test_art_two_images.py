import json

from lantool.game_directory import load_catalog, save_catalog


def _setup(tmp_path):
    root, art = tmp_path / "games", tmp_path / "art"
    folder = root / "Demo"
    folder.mkdir(parents=True)
    art.mkdir()
    (folder / "demo.exe").write_bytes(b"MZ")
    (art / "demo-1.png").write_bytes(b"cover")
    (art / "demo-1_icon.png").write_bytes(b"icon")
    return root, art, folder


def _manifest(folder, art, **extra):
    return {"id": "demo-1", "name": "Demo", "exe": "demo.exe", "exe_required": True,
            "args": [], "_game_dir": str(folder), "enabled": True,
            "_art_path": str(art / "demo-1.png"), **extra}


def test_cover_and_exe_icon_persist_as_separate_images(tmp_path):
    root, art, folder = _setup(tmp_path)
    state = tmp_path / "state.json"
    save_catalog(state, {"demo-1": _manifest(
        folder, art, art_sha256="cover-hash", _icon_path=str(art / "demo-1_icon.png"),
        icon_sha256="icon-hash")})
    loaded = load_catalog(state, root, art)["demo-1"]
    assert loaded["_art_path"].endswith("demo-1.png") and loaded["art_sha256"] == "cover-hash"
    assert loaded["_icon_path"].endswith("demo-1_icon.png") and loaded["icon_sha256"] == "icon-hash"


def test_legacy_catalog_keeps_cover_hash_as_icon_hash(tmp_path):
    root, art, folder = _setup(tmp_path)
    state = tmp_path / "state.json"
    state.write_text(json.dumps([{"id": "demo-1", "name": "Demo", "folder": "Demo", "exe": "demo.exe",
                                  "enabled": True, "art": "demo-1.png", "icon_sha256": "cover-hash"}]))
    loaded = load_catalog(state, root, art)["demo-1"]
    assert loaded["art_sha256"] == loaded["icon_sha256"] == "cover-hash"
    assert "_icon_path" not in loaded


def test_missing_icon_file_falls_back_to_cover_hash(tmp_path):
    root, art, folder = _setup(tmp_path)
    state = tmp_path / "state.json"
    save_catalog(state, {"demo-1": _manifest(
        folder, art, art_sha256="cover-hash", _icon_path=str(art / "demo-1_icon.png"),
        icon_sha256="icon-hash")})
    (art / "demo-1_icon.png").unlink()
    loaded = load_catalog(state, root, art)["demo-1"]
    assert "_icon_path" not in loaded and loaded["icon_sha256"] == "cover-hash"
