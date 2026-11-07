"""Diagnostics data model: one Report made of independent CheckResults.

Mirrors the sections of Connection Check.ps1. A failing check never aborts the
report; it is recorded as status="error" with the exception message.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional

OK, WARN, FAIL, ERROR, SKIPPED = "ok", "warn", "fail", "error", "skipped"


@dataclass
class CheckResult:
    name: str
    status: str = OK
    data: Any = None
    summary: str = ""
    error: str = ""
    duration_s: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Report:
    utc: str
    computer: str
    results: list = field(default_factory=list)

    def get(self, name: str) -> Optional[CheckResult]:
        return next((r for r in self.results if r.name == name), None)

    @property
    def worst(self) -> str:
        order = [OK, SKIPPED, WARN, FAIL, ERROR]
        return max((r.status for r in self.results), key=order.index, default=OK)

    def to_dict(self) -> dict:
        return {"utc": self.utc, "computer": self.computer,
                "worst": self.worst, "checks": [r.to_dict() for r in self.results]}


@dataclass
class Check:
    """name: stable id (matches the .ps1 section). run(report_so_far) -> data or CheckResult."""
    name: str
    title: str
    run: Callable[[Report], Any]
    timeout_s: float = 15.0


def elapsed_since(t0: float) -> float:
    return round(time.monotonic() - t0, 3)
