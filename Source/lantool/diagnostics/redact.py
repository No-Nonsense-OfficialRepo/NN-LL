"""Strip secrets from anything that goes into a diagnostics report.

The report is meant to be sent to someone else, so auth tokens and identity
secrets must never appear. Redaction is applied recursively to the data and to
error strings; it is deliberately conservative (key names + token-shaped text).
"""
from __future__ import annotations
import re
from typing import Any

REDACTED = "[redacted]"
_SECRET_KEY = re.compile(r"(secret|token|auth|password|passwd|private|identity|apikey|api_key)", re.I)
_PATTERNS = [
    re.compile(r"(X-ZT1-Auth\s*[:=]\s*)\S+", re.I),
    re.compile(r"((?:token|secret|password|authtoken)\s*[:=]\s*)\S+", re.I),
    re.compile(r"\b[0-9a-fA-F]{10}:\d:[A-Za-z0-9+/=_:-]{40,}\b"),   # ZeroTier identity.secret form
]
_PROFILE = re.compile(r"(?i)([A-Z]:[\\/]Users[\\/])[^\\/\r\n\"]+")


def redact_text(text: str) -> str:
    for pat in _PATTERNS[:2]:
        text = pat.sub(lambda m: m.group(1) + REDACTED, text)
    text = _PATTERNS[2].sub(REDACTED, text)
    return _PROFILE.sub(lambda m: m.group(1) + "<user>", text)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, dict):
        return {k: (REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else redact(v))
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(v) for v in value]
    return value
