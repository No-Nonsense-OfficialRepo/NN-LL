"""Run checks in order, isolating failures, reporting progress, redacting output."""
from __future__ import annotations
import os
import copy
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Iterable, Optional

from .model import Check, CheckResult, Report, OK, ERROR, elapsed_since
from .redact import redact

_workers_lock = threading.Lock()
_active_checks: set[str] = set()
MAX_DIAGNOSTIC_WORKERS = 4


def _call(check: Check, report: Report):
    """Bound stuck workers; a timeout cannot terminate a Python thread safely."""
    box: dict = {}
    # Checks may read previous results, but a late worker must not mutate the
    # report after its timeout or while the next check is running.
    snapshot = copy.deepcopy(report)
    with _workers_lock:
        if check.name in _active_checks:
            raise RuntimeError('This diagnostic check is still running from an earlier attempt.')
        if len(_active_checks) >= MAX_DIAGNOSTIC_WORKERS:
            raise RuntimeError('Diagnostic worker limit reached; earlier checks are still running.')
        _active_checks.add(check.name)

    def target():
        try:
            box["out"] = copy.deepcopy(check.run(snapshot))
        except BaseException as exc:                       # noqa: BLE001 - recorded, not raised
            box["exc"] = exc
        finally:
            with _workers_lock:
                _active_checks.discard(check.name)

    t = threading.Thread(target=target, name=f"diag-{check.name}", daemon=True)
    try:
        t.start()
    except BaseException:
        with _workers_lock:
            _active_checks.discard(check.name)
        raise
    t.join(check.timeout_s)
    if t.is_alive():
        raise TimeoutError(f"Timed out after {check.timeout_s:g}s")
    if "exc" in box:
        raise box["exc"]
    return box.get("out")


def run_checks(checks: Iterable[Check],
               progress: Optional[Callable[[str, int, int], None]] = None) -> Report:
    checks = list(checks)
    report = Report(utc=datetime.now(timezone.utc).isoformat(),
                    computer=os.environ.get("COMPUTERNAME") or socket.gethostname())
    for i, check in enumerate(checks, 1):
        if progress:
            progress(check.title, i, len(checks))
        t0 = time.monotonic()
        try:
            out = _call(check, report)
            res = out if isinstance(out, CheckResult) else CheckResult(check.name, OK, out)
            res.name = check.name
            res.data = redact(res.data)                    # redact every result, including self-built ones
            res.summary = redact(res.summary)
        except Exception as exc:                           # one bad check never kills the report
            res = CheckResult(check.name, ERROR, error=redact(str(exc)) or type(exc).__name__)
        res.duration_s = elapsed_since(t0)
        report.results.append(res)
    return report
