"""One-click connection diagnostics (in-app port of Connection Check.ps1)."""
from .model import Check, CheckResult, Report, OK, WARN, FAIL, ERROR, SKIPPED
from .runner import run_checks
from .redact import redact, redact_text

__all__ = ["Check", "CheckResult", "Report", "run_checks", "redact", "redact_text",
           "OK", "WARN", "FAIL", "ERROR", "SKIPPED"]
