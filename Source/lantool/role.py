"""Single source of truth for whether this process is the Host or the Client.

Precedence: an explicit ``--host`` / ``--client`` flag, then a frozen
executable whose name contains ``host``, then the Client default.
"""
from __future__ import annotations

from pathlib import Path
import sys

HOST = "host"
CLIENT = "client"


def detect_role(argv=None, exe_stem=None, frozen=None) -> str:
    argv = sys.argv if argv is None else argv
    frozen = bool(getattr(sys, "frozen", False)) if frozen is None else frozen
    if exe_stem is None:
        exe_stem = Path(sys.executable).stem
    if "--host" in argv and "--client" not in argv:
        return HOST
    if "--client" in argv:
        return CLIENT
    if frozen and "host" in str(exe_stem).lower():
        return HOST
    return CLIENT
