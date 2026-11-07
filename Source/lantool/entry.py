"""Shared start-up for the Host, Client and development entry points.

run_host.py and run_client.py pin the role explicitly (a --host / --client flag),
so a release never depends on its file name. run_launcher.py passes no role and
keeps the old behaviour for development (flag, else exe name, else Client).
"""
from __future__ import annotations

import sys
from pathlib import Path

# Special modes that parse argv exactly; the role flag must not be added to them.
_PASSTHROUGH = ("--lan-admin-action", "--vla-diagnose")


def apply_role(role, argv):
    """Return argv with an explicit role flag unless the caller chose one or this is a special mode."""
    if role not in ("host", "client") or len(argv) < 1:
        return list(argv)
    if len(argv) > 1 and argv[1] in _PASSTHROUGH:
        return list(argv)
    if "--host" in argv or "--client" in argv:
        return list(argv)
    return [argv[0], f"--{role}", *argv[1:]]


def run(role=None):
    sys.argv[:] = apply_role(role, sys.argv)
    if sys.argv[1:] == ['--vla-diagnose']:
        import json
        import traceback
        from silent_tunnel.local import LocalClient
        report = {}
        try:
            status = LocalClient().status()
            report = {'online': status.get('online'), 'has_address': bool(status.get('address'))}
        except Exception:
            report = {'error': traceback.format_exc()}
        target = Path(sys.executable).parent / 'vla-diagnostic.json'
        target.write_text(json.dumps(report, indent=2), encoding='utf-8')
        raise SystemExit(0 if report.get('has_address') else 1)
    if len(sys.argv) == 3 and sys.argv[1] == "--lan-admin-action":
        from silent_tunnel.admin_actions import run_admin_child
        raise SystemExit(run_admin_child(sys.argv[2]))

    from .single_instance import already_running, is_preview, launcher_role, show_existing
    if not is_preview() and already_running(launcher_role()):
        show_existing(launcher_role())
        raise SystemExit(0)

    local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
    if not getattr(sys, "frozen", False) and local_qt.is_dir():
        sys.path.insert(0, str(local_qt))
    from .qt.main import main
    raise SystemExit(main())
