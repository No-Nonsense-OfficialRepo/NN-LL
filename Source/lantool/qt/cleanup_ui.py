"""Cleanup and VLA-wipe actions for the Qt bridge.

Plain functions that take the bridge as their first argument. The QML-facing
Slot methods stay on LauncherBridge in bridge.py and delegate here.
"""
from __future__ import annotations

import threading

from PySide6.QtWidgets import QMessageBox

from .. import launcher as core


def wipe_vla(bridge) -> None:
    if bridge._preview:
        bridge.ui_message('showinfo', 'Design preview', 'VLA removal is disabled in preview mode.')
        return
    if bridge.busy or bridge._wiping or bridge._closing:
        return
    if core._other_launcher_running(bridge.role):
        bridge.ui_message('showinfo', 'Close the other launcher first',
                          'Please close the other launcher on this PC before wiping VLA.')
        return
    answer = QMessageBox.warning(None, 'Repair Network/Wipe VLA?',
        'Disconnect the room, uninstall launcher-owned VLA, and clear launcher data, '
        'including player details, room keys, trust, logs, game registrations and caches? '
        'Only theme and resolution settings will remain. Launcher files and game directories are kept. '
        'Other applications and their shared network driver are kept. '
        'The launcher closes afterward. Reopen it to set up VLA again. Windows may require a restart. Continue?',
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
        QMessageBox.StandardButton.Cancel)
    if answer != QMessageBox.StandardButton.Yes:
        return
    bridge._wiping = True
    bridge.busy = True
    bridge._dialog = {}
    bridge._status = 'Removing launcher VLA from this PC…'
    bridge._clear_download_queue()
    bridge.publish()
    protected = [bridge.game_root, core.GAME_FILES_ROOT]
    protected.append(getattr(bridge, '_launcher_upgrade_download', None))
    protected += [m.get('install_dir') or m.get('_dir') for m in bridge.library.values()]
    protected += [m.get('install_dir') or m.get('_dir') for m in getattr(bridge, 'game_catalog', {}).values()]
    from ..appdirs import app_root
    application = app_root()
    protected += [application / name for name in ('Host.exe', 'Client.exe', 'Quick Start.exe', 'Launcher Bin')]

    def work():
        result = {}
        try:
            # Stop discovery/recovery before removing the driver so it cannot rejoin.
            bridge.runtime.stop()
            if bridge.runtime.thread.is_alive():
                raise RuntimeError('Network tasks are still stopping. Close the launcher and retry.')
            # Diagnostic workers can save a report outside the network runtime.
            # Drain them before deletion so they cannot recreate cleared data.
            for name in ('_diag_thread', '_diag_fix_thread'):
                worker = getattr(bridge, name, None)
                if worker and worker.is_alive():
                    bridge.after(0, reset_progress, bridge, 'Waiting for the current network check to finish…')
                    worker.join(timeout=60)
                    if worker.is_alive():
                        raise RuntimeError('A network check is still running. Launcher data was kept. Retry after it finishes.')
            core.AdapterSwitcher(core.APP_DIR / 'vla-adapter-state.json').restore()
            from silent_tunnel.admin_actions import run_elevated
            result = run_elevated('wipe_vla')
            if not isinstance(result.get('report'), dict) or 'issues' not in result['report']:
                raise RuntimeError('VLA cleanup did not return a verification report. Launcher data was kept.')
            if not result['report']['issues']:
                from ..reset_data import reset_data
                import logging
                logging.shutdown()
                bridge.after(0, reset_progress, bridge, 'Clearing launcher data; keeping games, theme and resolution…')
                reset_data(core.APP_DIR, protected)
            bridge.after(0, wipe_finished, bridge, result, '')
        except Exception as exc:
            bridge.after(0, wipe_finished, bridge, result, str(exc))
    threading.Thread(target=work, name='vla-wipe', daemon=True).start()


def reset_progress(bridge, text):
    bridge._status = text
    bridge.publish()


def wipe_finished(bridge, result, error) -> None:
    report = result.get('report', {})
    issues = report.get('issues', [])
    if error:
        message = 'VLA removal could not finish.\n\n' + error
    elif issues:
        message = 'VLA removal is incomplete. Restart Windows and retry.\n\n' + '\n'.join(issues)
    else:
        try:
            from PySide6.QtCore import QSettings
            from ..reset_data import reset_preferences
            reset_preferences(QSettings('NN LAN Launcher', 'NN LAN Launcher'))
            reset_preferences(QSettings('Gamer Utility', 'Gamer Utility'))
        except Exception as exc:
            error = str(exc)
        message = ('Network reset finished. Launcher data and VLA were removed. '
                   'Theme, resolution, launcher files and game directories were kept. Reopen the launcher to set up again.')
        if error:
            message = 'Preferences could not be fully reset.\n\n' + error
    if report.get('reboot'):
        message += '\n\nRestart Windows before reinstalling VLA.'
    if error or issues:
        QMessageBox.warning(None, 'VLA removal needs attention', message)
    else:
        QMessageBox.information(None, 'VLA removed', message)
    bridge._finish_close()


def cleanup_pc(bridge) -> None:
    """'Clean up this PC': show the dry-run plan in the launcher, and wait for Yes before anything changes."""
    if bridge._preview or bridge.busy or bridge.room or bridge._beacon_joining or getattr(bridge, '_closing', False):
        return
    if core._other_launcher_running(getattr(bridge, 'role', 'client')):
        bridge.ui_message('showinfo', 'Close the other launcher first', 'Close the other launcher on this PC before cleanup.')
        return
    try:
        from silent_tunnel.cleanup import plan
        lines = plan()
    except Exception as exc:
        bridge.ui_message('showerror', 'Clean up this PC', f"Couldn't check this PC: {exc or type(exc).__name__}")
        return
    bridge._cleanup_confirm = {"lines": [str(line) for line in lines]}
    bridge.publish()


def cancel_cleanup(bridge) -> None:
    bridge._cleanup_confirm = None
    bridge.publish()


def confirm_cleanup(bridge) -> None:
    """Yes in the launcher's own confirmation: run the one elevated cleanup."""
    if not bridge._cleanup_confirm or bridge.busy:
        return
    bridge._cleanup_confirm = None
    if (bridge.room or bridge._beacon_joining or getattr(bridge, '_closing', False)
            or getattr(bridge, '_wiping', False)
            or core._other_launcher_running(getattr(bridge, 'role', 'client'))):
        bridge.publish()
        bridge.ui_message('showinfo', 'Cleanup cancelled', 'Leave the room and close the other launcher before cleanup.')
        return
    bridge.busy = True
    bridge.publish()

    def work():
        try:
            from silent_tunnel.cleanup import run
            bridge.after(0, cleanup_done, bridge, run(), "")
        except Exception as exc:
            bridge.after(0, cleanup_done, bridge, None, str(exc) or type(exc).__name__)
    try:
        threading.Thread(target=work, name="pc-cleanup", daemon=True).start()
    except Exception as exc:
        cleanup_done(bridge, None, str(exc) or type(exc).__name__)


def cleanup_done(bridge, result, error) -> None:
    bridge.busy = False
    bridge.publish()
    if error or not result:
        bridge.ui_message('showerror', 'Clean up this PC', f"Cleanup failed: {error}")
        return
    removed = "\n".join(result.get("removed", [])) or "Nothing was removed."
    left = "\n".join(result.get("left", []))
    text = "Removed:\n" + removed + ("\n\nLeft alone:\n" + left if left else "")
    bridge.ui_message('showinfo', 'Clean up this PC', text)
