"""Host-owned game catalog for folders stored in the launcher's Game Directory."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path, PurePosixPath

from .manifests.loader import ID_RE


def scan_game_folders(root: Path) -> list[Path]:
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    return sorted((p for p in root.iterdir() if p.is_dir() and not p.is_symlink()),
                  key=lambda p: p.name.casefold())


def find_game_folder(root: Path, exe_rel: str, exe_size: int, preferred: Path | None = None,
                     exe_sha256: str | None = None, *, cancelled=None, reserved=()) -> Path | None:
    """Locate existing installations, including a selected game folder or wrapper folders.

    Other games' folders cannot be reused. A mismatched executable is only a
    repair target inside this game's preferred installation folder.
    """
    from .filesync.index import check_cancelled
    check_cancelled(cancelled)
    if not isinstance(exe_rel, str):
        return None
    rel = PurePosixPath(exe_rel.replace("\\", "/"))
    if rel.is_absolute() or not rel.parts or any(part in ("", ".", "..") for part in rel.parts) \
            or ":" in exe_rel:
        return None
    root = Path(root).resolve()
    reserved = {Path(folder).resolve() for folder in reserved}
    folders = scan_game_folders(root)
    candidates = []
    if preferred is not None:
        preferred = Path(preferred).resolve()
        if preferred.parent == root and preferred.is_dir():
            candidates.append(preferred)
    candidates.append(root)
    candidates.extend(folder for folder in folders
                      if all(folder.resolve() != candidate for candidate in candidates))
    # ZIP extraction often adds another folder around the actual installation.
    # Keep this bounded; never walk entire game trees to identify a launcher.
    for folder in folders:
        check_cancelled(cancelled)
        try:
            candidates.extend(child for child in folder.iterdir()
                              if child.is_dir() and not child.is_symlink())
        except OSError:
            continue
    fallback = None
    for folder in candidates:
        check_cancelled(cancelled)
        try:
            exe = folder.joinpath(*rel.parts).resolve()
            if folder in reserved or any(owner != root and owner in exe.parents for owner in reserved):
                continue
            if folder.resolve() not in exe.parents or exe.name.casefold() != rel.name.casefold() or not exe.is_file():
                continue
            if exe.stat().st_size == exe_size:
                if not exe_sha256:
                    return folder
                from .install_manifest import matches
                if matches(folder, {'exe': exe_rel, 'exe_sha256': exe_sha256}, cancelled=cancelled):
                    return folder
            if fallback is None and preferred is not None and preferred in exe.parents:
                fallback = folder
        except OSError:
            continue
    return fallback


def game_id_for(folder: Path) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", folder.name.casefold()).strip("-_") or "game"
    slug = slug[:42].rstrip("-_") or "game"
    return f"{slug}-{hashlib.sha256(str(folder.resolve()).casefold().encode()).hexdigest()[:6]}"


_BAD_FOLDER_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
_RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}
CLIENT_DIRS_FILE = "client_game_dirs.json"


def safe_folder_name(name) -> str:
    """A game's display name made safe as one Windows folder name (no reserved characters or device names)."""
    text = _BAD_FOLDER_CHARS.sub(" ", str(name or ""))
    text = re.sub(r"\s+", " ", text).strip(" .")
    text = text[:48].rstrip(" .")  # leave room for the game's own nested paths under Windows' length limit
    if not text:
        return "Game"
    if text.split(".")[0].strip().casefold() in _RESERVED_NAMES:
        text += " game"
    return text


def _plain_component(value) -> bool:
    return (isinstance(value, str) and value not in ("", ".", "..") and value == Path(value).name
            and not _BAD_FOLDER_CHARS.search(value) and not value.endswith((" ", ".")))


def _occupied(path: Path) -> bool:
    """True when something other than an empty folder already sits at path."""
    try:
        if not path.exists():
            return False
        return not path.is_dir() or any(path.iterdir())
    except OSError:
        return True


def assign_client_folders(root: Path, state_path: Path, games) -> dict[str, Path]:
    """Choose each game's download folder under root: its display name, not its internal id.

    The choice is made once per game and saved in state_path, so a restart or a changed library never moves a
    download. A folder already named after the game's id (the old scheme) keeps being used. A suffix like "(2)" is
    added only when another game already has the name, or an unrelated non-empty folder already sits there.
    games is an iterable of (game_id, display_name).
    """
    root, state_path = Path(root), Path(state_path)
    try:
        raw = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    saved = {str(k): v for k, v in raw.items() if _plain_component(v)} if isinstance(raw, dict) else {}
    names = dict(saved)
    claimed = {value.casefold() for value in names.values()}
    result: dict[str, Path] = {}
    for gid, display in sorted(games, key=lambda item: item[0]):
        if gid in names:
            result[gid] = root / names[gid]
            continue
        if (root / gid).is_dir():  # a download made before names were used
            chosen = gid
        else:
            base = safe_folder_name(display)
            chosen, n = base, 1
            while (chosen.casefold() in claimed or _occupied(root / chosen)) and n < 1000:
                n += 1
                chosen = f"{base} ({n})"
            if n >= 1000:
                chosen = gid
        names[gid] = chosen
        claimed.add(chosen.casefold())
        result[gid] = root / chosen
    if names != saved:
        tmp = state_path.with_suffix(state_path.suffix + ".tmp")
        try:
            state_path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(names, indent=1, sort_keys=True), encoding="utf-8")
            os.replace(tmp, state_path)
        except OSError:
            pass  # the choice still holds for this session; it is simply chosen again next time
    return result


def load_catalog(state_path: Path, game_root: Path, art_root: Path) -> dict[str, dict]:
    try:
        raw = json.loads(Path(state_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    root, art_root = Path(game_root).resolve(), Path(art_root).resolve()
    result = {}
    for item in raw if isinstance(raw, list) else []:
        try:
            gid = item["id"]
            folder_name = item["folder"]
            folder = (root / folder_name).resolve()
            exe_required = item.get('exe_required', True) is not False
            exe_rel = str(item.get("exe", "")).replace("\\", "/") if exe_required else ''
            exe = (folder / exe_rel).resolve()
            if not ID_RE.fullmatch(gid) or folder.parent != root or not folder.is_dir():
                continue
            if exe_required and (folder not in exe.parents or exe.suffix.casefold() != ".exe" or not exe.is_file()):
                continue
            manifest = {"id": gid, "name": str(item["name"])[:80] or folder.name,
                        "exe": exe_rel, "exe_required": exe_required,
                        "args": item.get("args", []) if exe_required and isinstance(item.get("args", []), list) else [],
                        "_game_dir": str(folder),
                        "install_dir": str(folder), "enabled": bool(item.get("enabled", False))}
            art_name = item.get("art")
            art_path = (art_root / str(art_name)).resolve() if art_name else None
            if art_path and art_root in art_path.parents and art_path.is_file():
                manifest["_art_path"] = str(art_path)
                # Legacy catalogs stored only icon_sha256, and it was the cover hash.
                manifest["art_sha256"] = item.get("art_sha256") or item.get("icon_sha256", "")
                manifest["icon_sha256"] = manifest["art_sha256"]
            icon_name = item.get("icon")
            icon_path = (art_root / str(icon_name)).resolve() if icon_name else None
            if icon_path and art_root in icon_path.parents and icon_path.is_file() and item.get("icon_sha256"):
                manifest["_icon_path"] = str(icon_path)
                manifest["icon_sha256"] = item["icon_sha256"]
            result[gid] = manifest
        except (KeyError, OSError, TypeError, ValueError):
            continue
    return result


def save_catalog(state_path: Path, library: dict[str, dict]) -> None:
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    items = []
    for m in sorted(library.values(), key=lambda item: item["name"].casefold()):
        items.append({"id": m["id"], "name": m["name"],
                      "folder": Path(m["_game_dir"]).name, "exe": m["exe"],
                      "exe_required": m.get('exe_required', True),
                      "args": m.get("args", []),
                      "enabled": bool(m.get("enabled")),
                      "art": Path(m["_art_path"]).name if m.get("_art_path") else None,
                      "art_sha256": m.get("art_sha256", ""),
                      "icon": Path(m["_icon_path"]).name if m.get("_icon_path") else None,
                      "icon_sha256": m.get("icon_sha256", "")})
    path = Path(state_path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(items, indent=2), encoding="utf-8")
    tmp.replace(path)
