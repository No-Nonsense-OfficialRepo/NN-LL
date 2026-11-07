"""Manifest loading, validation, templating and launch (Workstream E, F7)."""
from __future__ import annotations
import json, os, re, subprocess, sys
from pathlib import Path

ID_RE = re.compile(r"^[a-z0-9_\-]+$")
HASH_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


class ManifestError(ValueError):
    pass


def validate(m: dict) -> dict:
    if not isinstance(m.get('exe_required', True), bool):
        raise ManifestError('exe_required must be true or false')
    for k in ("id", "name") + (("exe",) if m.get('exe_required', True) else ()):
        if not isinstance(m.get(k), str) or not m[k]:
            raise ManifestError(f"missing or invalid '{k}'")
    if not ID_RE.match(m["id"]):
        raise ManifestError("id must match [a-z0-9_-]+")
    for p in m.get("ports", []):
        if p.get("proto") not in ("tcp", "udp") or not isinstance(p.get("port"), int) \
                or not 1 <= p["port"] <= 65535:
            raise ManifestError(f"bad port entry {p!r}")
    if "hash" in m and not HASH_RE.match(m["hash"]):
        raise ManifestError("hash must be sha256:<64 hex>")
    if not isinstance(m.get("args", []), list) or not isinstance(m.get("prerequisites", []), list):
        raise ManifestError("args/prerequisites must be lists")
    return m


def load_library(root) -> dict[str, dict]:
    """Every games/<x>/manifest.json (or games/<x>.json) becomes a library entry."""
    root = Path(root)
    out: dict[str, dict] = {}
    for f in sorted(list(root.glob("*/manifest.json")) + list(root.glob("*.json"))):
        try:
            m = validate(json.loads(f.read_text(encoding="utf-8")))
        except (ValueError, OSError) as e:
            print(f"skip {f}: {e}")
            continue
        m["_dir"] = str(f.parent)
        out[m["id"]] = m
    return out


def render(value: str, ctx: dict) -> str:
    return re.sub(r"\{(\w+)\}", lambda mo: str(ctx.get(mo.group(1), mo.group(0))), value)


def resolve_exe(m: dict) -> Path:
    if m.get('exe_required', True) is False:
        raise ManifestError('This shared folder has no launch executable.')
    base = Path(m.get("install_dir") or m.get("_dir", "."))
    exe = (base / m["exe"]).resolve()
    if base.resolve() not in exe.parents and exe != base.resolve():
        raise ManifestError("exe escapes install_dir")  # path traversal guard
    return exe


def build_command(m: dict, ctx: dict) -> list[str]:
    return [str(resolve_exe(m))] + [render(a, ctx) for a in m.get("args", [])]


def patch_config(m: dict, ctx: dict) -> dict[str, str]:
    return {k: render(v, ctx) for k, v in m.get("config_patch", {}).items()}


_RUNNING: dict = {}  # game id -> Popen of the game we started on this PC


def is_running(gid: str) -> bool:
    proc = _RUNNING.get(gid)
    return proc is not None and proc.poll() is None


def stop(gid: str) -> bool:
    """End the game we launched for gid, and its child processes. False when nothing was running."""
    proc = _RUNNING.pop(gid, None)
    if proc is None or proc.poll() is not None:
        return False
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"], capture_output=True,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    else:
        proc.kill()
    return True


def launch(m: dict, ctx: dict) -> subprocess.Popen:
    exe = resolve_exe(m)
    if not exe.exists():
        raise ManifestError(f"missing exe: {exe}")
    proc = subprocess.Popen(build_command(m, ctx), cwd=str(exe.parent))
    _RUNNING[m["id"]] = proc
    return proc
