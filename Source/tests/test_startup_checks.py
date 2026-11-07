"""Mocked-filesystem tests for lantool/startup_checks.py (WP-E). No real disk, OS or network access."""
import os

import pytest

from lantool import startup_checks as sc

ROOT = os.path.join("C:", "LanTool")  # no leading separator; string ops only, works on any OS


class FakeProbe:
    def __init__(self, files=(), dirs=(), dir_contents=None, marked=(), writable=True,
                 temp="C:\\Users\\u\\AppData\\Local\\Temp", version=(10, 0, 22631)):
        self.files = set(files)
        self.dirs = set(dirs)
        self.dir_contents = dir_contents or {}
        self.marked = set(marked)
        self._writable = writable
        self._temp = temp
        self._version = version
        self.calls = []

    def exists(self, path):
        return path in self.files or path in self.dirs

    def is_dir(self, path):
        return path in self.dirs

    def listdir(self, path):
        return list(self.dir_contents.get(path, []))

    def walk_files(self, root, skip):
        skipped = {s.casefold() for s in skip}
        for f in sorted(self.files):
            parts = f[len(root):].lstrip("\\/").split(os.sep)
            if parts and parts[0].casefold() in skipped:
                continue
            yield f

    def has_zone_mark(self, path):
        self.calls.append(path)
        return path in self.marked

    def writable(self, path):
        return self._writable

    def temp_dir(self):
        return self._temp

    def windows_version(self):
        return self._version


def healthy(**kw):
    """A complete, clean, writable install in a normal folder."""
    helper = os.path.join(ROOT, sc.HELPER_DIR)
    base = dict(
        files={os.path.join(ROOT, sc.HELPER_EXE), os.path.join(ROOT, "LanTool.exe")},
        dirs={helper},
        dir_contents={helper: ["runtime.dll"]},
    )
    base.update(kw)
    return FakeProbe(**base)


def ids(problems):
    return [p.id for p in problems]


# ---- happy path

def test_healthy_install_has_no_problems():
    assert sc.run(ROOT, portable=False, probe=healthy(), frozen=True) == []


def test_problem_is_a_named_tuple_with_four_fields():
    p = sc.Problem("x", sc.WARN, "msg", "hint")
    assert p.id == "x" and p.severity == "warn" and p.message == "msg" and p.fix_hint == "hint"
    assert tuple(p) == ("x", "warn", "msg", "hint")


# ---- downloaded-file mark

def test_zone_mark_found_is_reported():
    exe = os.path.join(ROOT, "LanTool.exe")
    probe = healthy(marked={exe})
    problems = sc.run(ROOT, portable=False, probe=probe, frozen=True)
    assert ids(problems) == ["downloaded_file_mark"]
    assert problems[0].severity == sc.WARN
    assert "Unblock" in problems[0].fix_hint


def test_zone_mark_skips_game_directory_and_data_folder():
    marked = os.path.join(ROOT, "Game Directory", "game.exe")
    probe = healthy(files={marked, os.path.join(ROOT, "LanTool.exe"),
                           os.path.join(ROOT, sc.HELPER_EXE)}, marked={marked},
                    dirs={os.path.join(ROOT, sc.HELPER_DIR)},
                    dir_contents={os.path.join(ROOT, sc.HELPER_DIR): ["a"]})
    assert "downloaded_file_mark" not in ids(sc.run(ROOT, False, probe=probe, frozen=True))
    assert marked not in probe.calls


def test_zone_check_only_reads_and_stops_at_first_hit():
    a, b = os.path.join(ROOT, "a.dll"), os.path.join(ROOT, "b.dll")
    probe = healthy(files={a, b}, marked={a, b})
    sc.check_zone_mark(ROOT, probe)
    assert len(probe.calls) == 1


def test_no_zone_mark_returns_none():
    assert sc.check_zone_mark(ROOT, healthy()) is None


# ---- path length and characters

def test_long_path_is_reported():
    long_root = "C:\\" + "a" * 210
    p = sc.check_path(long_root)
    assert p and p.id == "path_too_long" and p.severity == sc.WARN


def test_path_at_limit_is_fine():
    assert sc.check_path("C:\\" + "a" * (sc.MAX_PATH_LEN - 3)) is None


@pytest.mark.parametrize("root", [
    "C:\\Tools;evil\\LanTool",
    "C:\\Tools!\\LanTool",
    "C:\\100%\\LanTool",
    "C:\\Téléchargements\\LanTool",
])
def test_unusual_characters_are_reported(root):
    p = sc.check_path(root)
    assert p and p.id == "path_unusual"


def test_plain_spaces_and_hyphens_are_fine():
    assert sc.check_path("C:\\My Apps\\LAN-Launcher") is None


# ---- runtime / Helper folder

def test_missing_helper_exe_is_error():
    probe = healthy(files={os.path.join(ROOT, "LanTool.exe")})
    p = sc.check_runtime(ROOT, probe, frozen=True)
    assert p and p.id == "runtime_incomplete" and p.severity == sc.ERROR
    assert sc.HELPER_EXE in p.message


def test_missing_helper_folder_is_error():
    probe = healthy(dirs=set())
    p = sc.check_runtime(ROOT, probe, frozen=True)
    assert p and "Helper folder" in p.message


def test_empty_helper_folder_is_incomplete():
    helper = os.path.join(ROOT, sc.HELPER_DIR)
    probe = healthy(dir_contents={helper: []})
    p = sc.check_runtime(ROOT, probe, frozen=True)
    assert p and "empty" in p.message


def test_runtime_not_checked_for_source_runs():
    assert sc.check_runtime(ROOT, FakeProbe(), frozen=False) is None


# ---- app folder writable

def test_read_only_folder_without_portable_is_error():
    p = sc.check_writable(ROOT, FakeProbe(writable=False), portable=False)
    assert p and p.id == "app_folder_read_only" and p.severity == sc.ERROR


def test_read_only_folder_in_portable_mode_is_left_to_appdirs():
    assert sc.check_writable(ROOT, FakeProbe(writable=False), portable=True) is None


def test_writable_folder_is_fine():
    assert sc.check_writable(ROOT, FakeProbe(writable=True), portable=False) is None


# ---- zip / temp preview

def test_running_from_temp_is_error():
    root = "C:\\Users\\u\\AppData\\Local\\Temp\\LanTool"
    p = sc.check_preview_location(root, FakeProbe(temp="C:\\Users\\u\\AppData\\Local\\Temp"))
    assert p and p.id == "running_from_zip_or_temp" and p.severity == sc.ERROR


def test_temp_prefix_must_be_a_whole_folder_name():
    # "...\Temp2\..." is not inside %TEMP%
    root = "C:\\Users\\u\\AppData\\Local\\Temp2\\LanTool"
    assert sc.check_preview_location(root, FakeProbe(temp="C:\\Users\\u\\AppData\\Local\\Temp")) is None


def test_running_from_inside_zip_path_is_error():
    p = sc.check_preview_location("D:\\Downloads\\LanTool.zip\\LanTool", FakeProbe(temp="C:\\Temp"))
    assert p and p.id == "running_from_zip_or_temp"


def test_7zip_temp_extract_folder_is_error():
    p = sc.check_preview_location("C:\\Apps\\7zO1A2B3C\\LanTool", FakeProbe(temp="C:\\Temp"))
    assert p and p.id == "running_from_zip_or_temp"


def test_normal_install_location_is_fine():
    assert sc.check_preview_location("C:\\Apps\\LanTool", FakeProbe(temp="C:\\Users\\u\\Temp")) is None


# ---- Windows version

def test_windows_8_1_is_too_old():
    p = sc.check_windows_version(FakeProbe(version=(6, 3, 9600)))
    assert p and p.id == "windows_too_old" and p.severity == sc.ERROR


def test_windows_10_is_ok():
    assert sc.check_windows_version(FakeProbe(version=(10, 0, 19045))) is None


def test_windows_11_is_ok():
    assert sc.check_windows_version(FakeProbe(version=(10, 0, 22631))) is None


def test_unknown_os_is_not_reported():
    assert sc.check_windows_version(FakeProbe(version=None)) is None


# ---- run(): ordering and combination

def test_run_lists_errors_before_warnings():
    marked = os.path.join(ROOT, "LanTool.exe")
    probe = healthy(marked={marked}, writable=False)
    problems = sc.run(ROOT, portable=False, probe=probe, frozen=True)
    assert ids(problems) == ["app_folder_read_only", "downloaded_file_mark"]
    assert [p.severity for p in problems] == [sc.ERROR, sc.WARN]


def test_run_reports_several_problems_at_once():
    probe = FakeProbe(version=(6, 1, 7601), writable=False, temp="C:\\Temp")
    problems = sc.run("C:\\Temp\\LanTool", portable=False, probe=probe, frozen=True)
    assert set(ids(problems)) >= {"running_from_zip_or_temp", "windows_too_old",
                                  "app_folder_read_only", "runtime_incomplete"}


def test_run_accepts_pathlike_root(tmp_path):
    # real-probe path is not used here; just ensure os.fspath works with a pathlike
    root = tmp_path / "LanTool"
    r = os.fspath(root)
    probe = FakeProbe(
        files={os.path.join(r, sc.HELPER_EXE)},
        dirs={os.path.join(r, sc.HELPER_DIR)},
        dir_contents={os.path.join(r, sc.HELPER_DIR): ["a.dll"]},
        temp="C:\\Temp",
    )
    assert sc.run(root, portable=True, probe=probe, frozen=True) == []


def test_run_never_raises_for_missing_probe_answers():
    class Bare(FakeProbe):
        def walk_files(self, root, skip):
            return iter(())
    assert sc.run(ROOT, False, probe=Bare(), frozen=False) == []
