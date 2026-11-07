"""First-run and environment checks (WP-E).

Pure checks. Every read of the filesystem or OS goes through a *probe* object so the tests can
mock it. Nothing here runs elevated, writes outside a probe, or touches the network.

Public interface:
    run(app_root, portable, *, probe=None, frozen=None) -> list[Problem]
    Problem = (id, severity, message, fix_hint)
"""
from __future__ import annotations

import os
import re
import sys
import tempfile
from typing import Iterable, Iterator, NamedTuple, Optional

ERROR = "error"
WARN = "warn"

SKIP_DIRS = ("Game Directory", "LanTool-data")   # same skip list as silent_tunnel/prepare.py
MAX_PATH_LEN = 200                               # Windows MAX_PATH is 260; keep headroom for files inside
MAX_FILES_SCANNED = 5000
HELPER_EXE = "LAN Helper.exe"
HELPER_DIR = "Helper"
MIN_WINDOWS = (10, 0)

_UNUSUAL_CHARS = re.compile(r"[;!%&^#$@{}\[\]~`=+]")
_TEMP_PREVIEW = re.compile(r"(?i)[\\/](7zo[0-9a-f]+|rar\$[^\\/]+|temp1_[^\\/]+|\.zip)([\\/]|$)")
_ZIP_SUFFIX = re.compile(r"(?i)\.zip([\\/]|$)")


class Problem(NamedTuple):
    id: str
    severity: str
    message: str
    fix_hint: str


# ---------------------------------------------------------------- probe

class RealProbe:
    """The only class that touches the real OS. Not used by the tests."""

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def is_dir(self, path: str) -> bool:
        return os.path.isdir(path)

    def listdir(self, path: str) -> list:
        try:
            return os.listdir(path)
        except OSError:
            return []

    def walk_files(self, root: str, skip: Iterable[str]) -> Iterator[str]:
        skipped = {s.casefold() for s in skip}
        for current, dirs, files in os.walk(root):
            if os.path.normcase(current) == os.path.normcase(root):
                dirs[:] = [d for d in dirs if d.casefold() not in skipped]
            for name in files:
                yield os.path.join(current, name)

    def has_zone_mark(self, path: str) -> bool:
        # Mark-of-the-Web alternate stream. Reads only; never removes it.
        if os.name != "nt":
            return False
        return os.path.exists(path + ":Zone.Identifier")

    def writable(self, path: str) -> bool:
        return os.access(path, os.W_OK)

    def temp_dir(self) -> str:
        return tempfile.gettempdir()

    def windows_version(self) -> Optional[tuple]:
        if os.name != "nt":
            return None
        v = sys.getwindowsversion()
        return (v.major, v.minor, v.build)


# ---------------------------------------------------------------- checks

def check_zone_mark(root: str, probe) -> Optional[Problem]:
    hits = 0
    scanned = 0
    for path in probe.walk_files(root, SKIP_DIRS):
        scanned += 1
        if probe.has_zone_mark(path):
            hits += 1
            break
        if scanned >= MAX_FILES_SCANNED:
            break
    if not hits:
        return None
    return Problem(
        "downloaded_file_mark", WARN,
        "Windows marks files from the internet as downloaded, and this app folder still has that mark. "
        "Windows may block or warn about parts of the app.",
        "Run 'Unblock downloaded files.cmd' in Launcher Bin > Release, or open Settings > Prepare this PC. "
        "No administrator rights are needed for the unblock step.",
    )


def check_path(root: str) -> Optional[Problem]:
    if len(root) > MAX_PATH_LEN:
        return Problem(
            "path_too_long", WARN,
            f"The app is in a very long folder path ({len(root)} characters). Windows may fail on files inside it.",
            "Move the app folder to a short path such as C:\\LanTool or D:\\LanTool.",
        )
    if _UNUSUAL_CHARS.search(root) or any(ord(c) > 127 for c in root):
        return Problem(
            "path_unusual", WARN,
            "The app folder path contains unusual characters (such as ; ! % & # or non-English letters). "
            "Some tools and firewall rules can fail with these.",
            "Move the app folder to a path made of plain letters, numbers, spaces and hyphens.",
        )
    return None


def check_runtime(root: str, probe, frozen: bool) -> Optional[Problem]:
    if not frozen:
        return None                       # source runs use the Python environment, not the Helper folder
    runtime = os.path.join(root, "Launcher Bin")
    if probe.is_dir(runtime):
        root = os.path.join(runtime, "Elevation")
    missing = []
    if not probe.exists(os.path.join(root, HELPER_EXE)):
        missing.append(HELPER_EXE)
    helper_dir = os.path.join(root, HELPER_DIR)
    if not probe.is_dir(helper_dir):
        missing.append(HELPER_DIR + " folder")
    elif not probe.listdir(helper_dir):
        missing.append(HELPER_DIR + " folder (empty)")
    if not missing:
        return None
    return Problem(
        "runtime_incomplete", ERROR,
        "Part of the app is missing: " + ", ".join(missing) + ". Some features will not work.",
        "Download the app again and extract the whole folder, keeping every file together. "
        "Do not move the .exe on its own.",
    )


def check_writable(root: str, probe, portable: bool) -> Optional[Problem]:
    if portable:
        return None                       # portable mode keeps its data inside the app folder, so the
                                          # folder must be writable; that is covered by appdirs.data_dir_problem
    if probe.writable(root):
        return None
    return Problem(
        "app_folder_read_only", ERROR,
        "The app folder is read-only, so the app cannot save its settings here.",
        "Move the app to a folder you own, such as Documents or Desktop, or to a writable USB drive. "
        "Then copy portable.flag next to the app if you want its data kept with it.",
    )


def check_preview_location(root: str, probe) -> Optional[Problem]:
    temp = probe.temp_dir()
    in_temp = bool(temp) and os.path.normcase(root).startswith(os.path.normcase(temp).rstrip("\\/") + os.sep)
    if in_temp or _TEMP_PREVIEW.search(root) or _ZIP_SUFFIX.search(root):
        return Problem(
            "running_from_zip_or_temp", ERROR,
            "The app is running from inside a zip file or a temporary folder. "
            "Its files will be removed when that preview closes, and settings will be lost.",
            "Extract the whole zip to a permanent folder first (right-click > Extract All), then open the app from there.",
        )
    return None


def check_windows_version(probe) -> Optional[Problem]:
    version = probe.windows_version()
    if version is None:                   # unknown OS (source run on another system): nothing to say
        return None
    if tuple(version[:2]) >= MIN_WINDOWS:
        return None
    return Problem(
        "windows_too_old", ERROR,
        "This Windows version is too old for the app. It needs Windows 10 or Windows 11.",
        "Update Windows through Settings > Windows Update, or use a PC with Windows 10 or 11.",
    )


# ---------------------------------------------------------------- entry point

def run(app_root, portable: bool, *, probe=None, frozen: Optional[bool] = None) -> list:
    """Run every check and return the problems found, errors first. Never raises for a bad folder."""
    probe = probe or RealProbe()
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    root = os.fspath(app_root)
    results = [
        check_path(root),
        check_preview_location(root, probe),
        check_windows_version(probe),
        check_runtime(root, probe, frozen),
        check_writable(root, probe, bool(portable)),
        check_zone_mark(root, probe),
    ]
    problems = [p for p in results if p is not None]
    problems.sort(key=lambda p: 0 if p.severity == ERROR else 1)
    return problems
