"""Run the default checks and save the JSON report (UI-independent, so it is testable)."""
from __future__ import annotations
import json
import time
from pathlib import Path
from typing import Callable, Optional

from .checks import default_checks
from .model import Report, WARN, FAIL
from .runner import run_checks

KEEP_REPORTS = 20
_PREFIX = "connection-check-"


def save_report(report: Report, directory, keep: int = KEEP_REPORTS) -> Path:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / time.strftime(f"{_PREFIX}%Y%m%d-%H%M%S.json")
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    for old in sorted(directory.glob(f"{_PREFIX}*.json"), reverse=True)[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
    return path


def summarize(report: Report, checks=None) -> list:
    """One short line per check: '<title>: <status>[ - <detail>]'."""
    titles = {c.name: c.title for c in (checks or [])}
    lines = []
    for r in report.results:
        detail = r.error or r.summary
        lines.append(f"{titles.get(r.name, r.name)}: {r.status}" + (f" - {detail}" if detail else ""))
    return lines


# check name -> (fix id, button label). Only safe, allow-listed fixes; each asks first / shows UAC.
FIXES = {"vlaService": ("restartVla", "Restart VLA"),
         "firewall": ("repairLan", "Repair LAN"),
         "pathDrift": ("firewallRepath", "Repair rules")}


def fix_for(result):
    """(fix id, label) when this result is fixable, else ('', '')."""
    if result.status not in (WARN, FAIL):
        return ("", "")
    fix = FIXES.get(result.name, ("", ""))
    # a missing VLA service cannot be fixed by restarting it
    if result.name == "vlaService" and result.status == FAIL:
        return ("", "")
    return fix


CHECK_DESCRIPTIONS = {
    "windows": "Windows version is supported (10 or later)",
    "timeStatus": "Windows time service is running",
    "clockOffsetSamples": "This PC's clock compared with network time",
    "networkProfile": "Public and Private networks are supported; firewall rules control access",
    "vlaService": "Background service for the virtual LAN adapter",
    "vlaStatus": "Whether the virtual LAN adapter is online",
    "networks": "Virtual LAN networks this PC is joined to",
    "peers": "Other PCs seen on the room network",
    "peerPaths": "Direct or relayed route to each peer",
    "roomListeners": "Room network ports open on this PC",
    "runningLaunchers": "Launcher copies running right now",
    "firewall": "Windows Firewall rules the launcher needs",
    "pathDrift": "Looks for older launcher copies in other folders",
    "dataDir": "Launcher data folder can be written to",
    "udpNatProbe": "UDP discovery traffic through your router",
    "recentJoinTiming": "Timings from recent room joins",
    "hostPorts": "Room ports listening on this PC",
    "hostFirewall": "Firewall rules needed to host a room",
    "hostUdpDiscovery": "Discovery requests answered on this PC",
}


def summarize_rows(report: Report, checks=None) -> list:
    """Structured rows for the UI: [{title, desc, status, detail, fix, fixLabel}].

    Worst first (fail/error, warn, ok, skipped); check order is kept within a severity."""
    titles = {c.name: c.title for c in (checks or [])}
    rows = []
    for r in report.results:
        fix, label = fix_for(r)
        rows.append({"title": titles.get(r.name, r.name), "desc": CHECK_DESCRIPTIONS.get(r.name, ""),
                     "status": r.status,
                     "detail": r.error or r.summary or "", "fix": fix, "fixLabel": label})
    rank = {"fail": 0, "error": 0, "warn": 1, "ok": 2, "skipped": 3}
    rows.sort(key=lambda row: rank.get(row["status"], 2))   # stable
    return rows


def report_text(header: str, worst: str, lines, path: str = "") -> str:
    """Plain-text report for pasting into chat/support. Redacted again as a last guard."""
    from .redact import redact_text
    out = [header, f"Overall: {worst or 'not run'}", ""] + list(lines or [])
    if path:
        out += ["", f"Saved: {Path(path).name}"]
    return redact_text("\n".join(out))


def run_and_save(directory, checks=None,
                 progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    checks = list(checks) if checks is not None else default_checks()
    report = run_checks(checks, progress)
    path = save_report(report, directory)
    return {"path": str(path), "worst": report.worst, "lines": summarize(report, checks),
            "rows": summarize_rows(report, checks),
            "report": report}
