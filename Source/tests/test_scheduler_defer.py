"""A paused peer is deferred briefly: no failure count, no request-limit drop, one log line per cooldown."""
import time

from lantool.filesync.scheduler import Scheduler


def test_defer_skips_source_without_penalty():
    scheduler = Scheduler()
    source = ("10.0.0.2", 47805, True)
    scheduler.success(source, 1024, 0.1)
    limit, rate = scheduler.limit, scheduler.sources[source][0]
    assert scheduler.defer(source, 2) is True
    assert scheduler.sources[source][1] == 0  # no failure recorded
    assert scheduler.sources[source][0] == rate  # measured speed kept
    assert scheduler.sources[source][2] > time.monotonic()
    assert scheduler.limit == limit  # request budget untouched


def test_defer_reports_first_call_only_during_cooldown():
    scheduler = Scheduler()
    source = ("10.0.0.3", 47805, True)
    assert scheduler.defer(source, 2) is True
    assert scheduler.defer(source, 2) is False


def test_deferred_source_sorts_after_ready_ones():
    scheduler = Scheduler()
    paused, ready = ("10.0.0.2", 47805, True), ("10.0.0.4", 47805, True)
    scheduler.defer(paused, 5)
    assert scheduler.order([paused, ready], 0)[0] == ready


def test_first_logs_once_per_key():
    scheduler = Scheduler()
    assert scheduler.first(("lacks", "a", "f")) is True
    assert scheduler.first(("lacks", "a", "f")) is False
    assert scheduler.first(("lacks", "b", "f")) is True
