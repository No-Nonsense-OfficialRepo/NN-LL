"""Diagnostics actions for the Qt bridge.

Plain functions that take the bridge as their first argument. The QML-facing
Slot methods stay on LauncherBridge in bridge.py and delegate here.
"""
from __future__ import annotations

import threading

from PySide6.QtWidgets import QApplication, QMessageBox

from .. import launcher as core


def copy_report(bridge) -> None:
    """Copy the last connection-check results (redacted); fall back to a short status summary."""
    from ..diagnostics.service import report_text
    d = bridge._diag or {}
    header = f"NN LAN Launcher {bridge.version if hasattr(bridge, 'version') else ''}".strip()
    if d.get("lines"):
        text = report_text(header, d.get("worst", ""), d["lines"], d.get("path", ""))
    else:
        text = report_text(header, "", [f"Status: {getattr(bridge, 'status', '')}",
                                        "No connection check has been run yet."])
    QApplication.clipboard().setText(text)


def run_ladder(bridge, address) -> None:
    """Walk the join path against one Host IP (typed or discovered)."""
    address = (address or "").strip()
    if not address:
        bridge._diag = {**bridge._diag, "error": "Enter the Host's IP address first."}
        bridge.publish()
        return
    trusted = getattr(bridge, "trusted_host_pub", None)

    def make_checks():
        from ..diagnostics.ladder import client_ladder_checks
        return client_ladder_checks(address, trusted_pub=trusted)
    bridge._start_diag(make_checks)


def host_check(bridge) -> None:
    """Probe this PC's own room the way a client would (host mode)."""
    def make_checks():
        from ..diagnostics.host_checks import host_checks
        return host_checks()
    bridge._start_diag(make_checks)


def run_fix(bridge, fix_id) -> None:
    """Run one safe fix from a Diagnostics row, then re-check. Public->Private asks first."""
    if bridge._preview or bridge._wiping or bridge._closing or bridge._diag.get("running") or bridge.busy:
        return
    if fix_id == "restartVla":
        kwargs = {"action": "restart_service"}
    elif fix_id == "repairLan":
        kwargs = {"action": "launcher_firewall"}
    elif fix_id == "firewallRepath":
        # re-points our rules at this exe and removes stale ones (apply_rules is idempotent)
        kwargs = {"action": "launcher_firewall"}
    elif fix_id == "setPrivate":
        public = list(getattr(bridge, "_public_profiles", []) or [])
        indexes = [int(p["InterfaceIndex"]) for p in public if str(p.get("InterfaceIndex", "")).isdigit()]
        if not indexes:
            bridge._diag = {**bridge._diag, "error": "Run the connection check first; no Public network was found."}
            bridge.publish()
            return
        names = ", ".join(str(p.get("name")) for p in public)
        answer = QMessageBox.question(
            None, "Set network to Private?",
            f"Windows treats '{names}' as a Public network, which can block LAN discovery. "
            "Switch it to Private? Only do this on a network you trust (home or LAN party). "
            "Windows will ask for permission.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel)
        if answer != QMessageBox.StandardButton.Yes:
            return
        kwargs = {"action": "network_private", "interface_indexes": indexes}
    else:
        return
    bridge._diag = {**bridge._diag, "running": True, "error": "", "step": "Applying fix… approve Windows permission if asked."}
    bridge.publish()

    def work():
        try:
            from silent_tunnel.admin_actions import run_elevated
            action = kwargs.pop("action")
            result = run_elevated(action, **kwargs)
            bridge.after(0, fix_done, bridge, result, "")
        except Exception as exc:
            bridge.after(0, fix_done, bridge, None, str(exc) or type(exc).__name__)
    bridge._diag_fix_thread = threading.Thread(target=work, name="diag-fix", daemon=True)
    bridge._diag_fix_thread.start()


def fix_done(bridge, result, error) -> None:
    if bridge._wiping or bridge._closing:
        return
    bridge._diag = {**bridge._diag, "running": False}
    if error or not (result or {}).get("ok", False):
        message = error or (result or {}).get("error") or "The fix did not complete."
        bridge._diag = {**bridge._diag, "error": f"Fix failed: {message}"}
        bridge.publish()
        return
    bridge._start_diag(None)  # re-check so the row turns green (or shows what is still wrong)


def start_diag(bridge, make_checks) -> None:
    if bridge._preview or bridge._wiping or bridge._closing or bridge._diag.get("running"):
        return
    bridge._diag = {"running": True, "step": "Starting…", "done": 0, "total": 0,
                    "lines": [], "rows": [], "path": "", "worst": "", "error": ""}
    bridge.publish()

    def progress(title, i, n):
        bridge.after(0, diag_progress, bridge, title, i, n)

    def work():
        try:
            from ..diagnostics.service import run_and_save
            checks = make_checks() if make_checks else None
            result = run_and_save(core.APP_DIR / "diagnostics", checks=checks, progress=progress)
            bridge.after(0, diag_done, bridge, result, "")
        except Exception as exc:
            bridge.after(0, diag_done, bridge, None, str(exc) or type(exc).__name__)
    bridge._diag_thread = threading.Thread(target=work, name="diagnostics", daemon=True)
    bridge._diag_thread.start()


def diag_progress(bridge, title, i, n) -> None:
    if bridge._wiping or bridge._closing:
        return
    bridge._diag = {**bridge._diag, "step": title, "done": i - 1, "total": n}
    bridge.publish()


def diag_done(bridge, result, error) -> None:
    if bridge._wiping or bridge._closing:
        return
    if error or not result:
        bridge._diag = {**bridge._diag, "running": False, "error": error or "No result"}
        bridge.publish()
        return
    report = result.get("report")
    found = report.get("networkProfile") if report else None
    bridge._public_profiles = ((found.data or {}).get("public") if found and isinstance(found.data, dict) else None) or []
    bridge._diag = {"running": False, "step": "", "done": 0, "total": 0, "error": "",
                    "lines": result["lines"], "rows": result.get("rows", []),
                    "path": result["path"], "worst": result["worst"]}
    bridge.publish()
