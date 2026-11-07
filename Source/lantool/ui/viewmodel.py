"""Library view-model: toolkit-agnostic, so the UI layer only renders it. Pure and unit-testable."""
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from ..manifests.loader import resolve_exe, ManifestError


@dataclass(frozen=True)
class Tile:
    id: str
    name: str
    installed: bool
    hovering: int
    playing: int
    badge: str


def _installed(m: dict) -> bool:
    try:
        return resolve_exe(m).exists()
    except ManifestError:
        return False


def badge_text(hovering: int, playing: int) -> str:
    # Hover counts are intentionally omitted; tiles report active play only.
    return f"\U0001F3AE {playing} playing" if playing else ""


class LibraryViewModel:
    def __init__(self, library: dict[str, dict]):
        self.library = library
        self._installed = {gid: _installed(m) for gid, m in library.items()}
        self.counts: dict = {"games": {}, "players": 0}

    def refresh_install_state(self):
        self._installed = {gid: _installed(m) for gid, m in self.library.items()}

    def update_counts(self, counts: dict) -> set[str]:
        """Store new counts; return ids of tiles whose badge changed (so the view redraws only those)."""
        old = self.counts.get("games", {})
        new = counts.get("games", {})
        self.counts = counts
        return {g for g in set(old) | set(new) | set(self.library)
                if old.get(g) != new.get(g) and g in self.library}

    def tile(self, gid: str) -> Tile:
        m, c = self.library[gid], self.counts.get("games", {}).get(gid, {})
        h, p = c.get("hovering", 0), c.get("playing", 0)
        return Tile(gid, m["name"], self._installed[gid], h, p, badge_text(h, p))

    def tiles(self, query: str = "") -> list[Tile]:
        q = query.lower()
        return [self.tile(g) for g, m in sorted(self.library.items(), key=lambda kv: kv[1]["name"].lower())
                if q in m["name"].lower()]
