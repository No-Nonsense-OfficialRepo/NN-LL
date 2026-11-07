"""Firewall path drift: our inbound rules point at a program that is no longer the running exe.

Rules are keyed to the launcher exe path (silent_tunnel.firewall.rule_names hashes the resolved
path), so moving the folder, renaming the exe or unpacking a new release beside the old one leaves
rules behind that cover nothing. `check` and `stale_rules` are pure: they take the rule list and
the current exe and touch the file system only through `exists`. `collect` is the one read-only
system call (Get-NetFirewallRule), used by the Diagnostics run.

A rule is a dict: {"name", "program", "enabled"(default True)}; other keys are ignored.

Stale reasons (see `classify`):
  missing        the rule's program file is gone (deleted folder, renamed or removed exe)
  older_release  the program sits in another folder whose name carries an older version (V1.5 vs V1.6)
  other_folder   the program exists, but in a different folder (moved or copied app)
A rule for another exe in the SAME folder (the Host/Client sibling) is not stale.
"""
from __future__ import annotations

import os
import re
from typing import Callable, Iterable, Optional

from .model import CheckResult, FAIL, OK, SKIPPED, WARN

CHECK_NAME = "path_drift"
FIX_ID = "firewall_repath"
RULE_PREFIX = "GamerUtility-"
MISSING, OLDER_RELEASE, OTHER_FOLDER, CURRENT, SIBLING = (
    "missing", "older_release", "other_folder", "current", "sibling")

_VERSION = re.compile(r"(?<![0-9A-Za-z])[Vv]?(\d+(?:\.\d+){1,3})(?![0-9])")


def _norm(path) -> str:
    return os.path.normcase(os.path.abspath(os.path.normpath(str(path)))) if path else ""


def _folder(path: str) -> str:
    return os.path.dirname(path)


def release_of(path) -> Optional[tuple]:
    """Version tuple read from the folder name, else the file name (e.g. 'Lan Launcher V1.6' -> (1, 6))."""
    path = str(path or "")
    for part in (os.path.basename(os.path.dirname(path)), os.path.basename(path)):
        match = _VERSION.search(part)
        if match:
            return tuple(int(piece) for piece in match.group(1).split("."))
    return None


def _current_names(current_exe) -> set:
    from silent_tunnel.firewall import rule_names      # lazy: firewall imports this module lazily too
    return set(rule_names(str(current_exe)))


def _ours(rule) -> bool:
    return isinstance(rule, dict) and str(rule.get("name", "")).startswith(RULE_PREFIX)


def classify(rule: dict, current_exe, exists: Callable[[str], bool] = os.path.exists) -> str:
    """CURRENT, SIBLING, MISSING, OLDER_RELEASE or OTHER_FOLDER for one of our rules."""
    program = _norm(rule.get("program"))
    exe = _norm(current_exe)
    if program and program == exe:
        return CURRENT
    if not program or not exists(program):
        return MISSING
    if _folder(program) == _folder(exe):
        return SIBLING
    mine, theirs = release_of(exe), release_of(program)
    if mine and theirs and theirs < mine:
        return OLDER_RELEASE
    return OTHER_FOLDER


def stale_rules(rules: Iterable[dict], current_exe, exists: Callable[[str], bool] = os.path.exists) -> list:
    """Our rules that no longer belong: each is the input dict plus a 'reason'. Rules for the current
    exe and for sibling exes in the same folder are never returned."""
    names = _current_names(current_exe)
    stale = []
    for rule in rules or []:
        if not _ours(rule):
            continue
        reason = classify(rule, current_exe, exists)
        if reason in (CURRENT, SIBLING):
            continue
        if rule.get("name") in names and reason == MISSING and not rule.get("program"):
            continue                                    # unreadable program field on a current-name rule
        stale.append({**rule, "reason": reason})
    return stale


def _describe(entry: dict) -> str:
    where = entry.get("program") or "an unknown program"
    return {MISSING: f"{where} no longer exists",
            OLDER_RELEASE: f"{where} is an older release folder",
            OTHER_FOLDER: f"{where} is in a different folder"}.get(entry["reason"], where)


def check(rules: Optional[Iterable[dict]], current_exe, exists: Callable[[str], bool] = os.path.exists) -> CheckResult:
    """WARN when old rules linger next to working ones; FAIL when the running exe has no rule of its own
    but rules for another path do (moved folder, new release, renamed exe: this copy is not covered)."""
    if not current_exe:
        return CheckResult(CHECK_NAME, SKIPPED, summary="Not running from a packaged launcher.")
    if rules is None:
        return CheckResult(CHECK_NAME, SKIPPED, summary="Couldn't read the firewall rules.")
    rules = [r for r in rules if _ours(r)]
    if not rules:
        return CheckResult(CHECK_NAME, SKIPPED, data={"stale": [], "current_rules": 0},
                           summary="No launcher firewall rules exist yet (the firewall check covers that).")
    names = _current_names(current_exe)
    covered = [r for r in rules if r.get("name") in names and r.get("enabled", True) is not False]
    stale = stale_rules(rules, current_exe, exists)
    data = {"current": str(current_exe), "current_rules": len(covered),
            "stale": [{"name": s.get("name"), "program": s.get("program"), "reason": s["reason"]} for s in stale]}
    if not stale:
        if covered:
            return CheckResult(CHECK_NAME, OK, data=data, summary="Firewall rules point at this launcher.")
        return CheckResult(CHECK_NAME, SKIPPED, data=data,
                           summary="Rules belong to a sibling exe in this folder; none for this one yet.")
    data["fix"] = FIX_ID
    first = _describe(stale[0])
    more = f" (+{len(stale) - 1} more)" if len(stale) > 1 else ""
    if len(covered) < len(names):
        return CheckResult(CHECK_NAME, FAIL, data=data,
                           summary=f"The firewall rules are for another copy of the launcher: {first}{more}. "
                                   "This copy isn't covered, so other PCs may not reach it. Click Fix to repair.")
    return CheckResult(CHECK_NAME, WARN, data=data,
                       summary=f"Old firewall rules are left behind: {first}{more}. Click Fix to clean up.")


def collect(current_exe=None, exists: Callable[[str], bool] = os.path.exists) -> CheckResult:
    """Read our rules (read-only, no admin) and run `check`. `current_exe` defaults to the running exe."""
    import sys
    if current_exe is None:
        current_exe = sys.executable if getattr(sys, "frozen", False) else None
    if not current_exe:
        return check([], None)
    from silent_tunnel.firewall import list_our_rules
    return check(list_our_rules(), current_exe, exists)
