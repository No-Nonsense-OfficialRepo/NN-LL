"""One adaptive request budget per download, shared by all files and pieces."""
import asyncio
import time


class Scheduler:
    def __init__(self, maximum=12):
        self.maximum = max(1, min(12, maximum))
        self.limit = min(4, self.maximum)
        self.active = 0
        self.condition = asyncio.Condition()
        self.sources = {}
        self.started = time.monotonic()
        self.bytes = 0
        self.previous_rate = None

    async def __aenter__(self):
        async with self.condition:
            await self.condition.wait_for(lambda: self.active < self.limit)
            self.active += 1

    async def __aexit__(self, *args):
        async with self.condition:
            self.active -= 1
            self.condition.notify_all()

    def success(self, source, count, elapsed):
        rate = count / max(elapsed, .001)
        old = self.sources.get(source, (0, 0, 0))
        self.sources[source] = (.7 * old[0] + .3 * rate, 0, 0)
        self.bytes += count
        now = time.monotonic()
        if now - self.started >= 2:
            rate = self.bytes / (now - self.started)
            if self.previous_rate is None or rate > self.previous_rate * 1.05:
                self.limit = min(self.maximum, self.limit + 1)
            elif rate < self.previous_rate * .85:
                self.limit = max(1, self.limit - 1)
            self.previous_rate = rate
            self.started, self.bytes = now, 0

    def failure(self, source):
        rate, failures, _ = self.sources.get(source, (0, 0, 0))
        failures += 1
        self.sources[source] = (rate, failures, time.monotonic() + min(30, 2 ** min(failures, 5)))
        self.limit = max(1, self.limit - 1)

    def defer(self, source, seconds):
        """Skip a source for a while without counting a failure or lowering the request limit (e.g. a paused peer).
        Returns True if the source was not already deferred, so callers can log just once per cooldown."""
        rate, failures, until = self.sources.get(source, (0, 0, 0))
        now = time.monotonic()
        self.sources[source] = (rate, failures, max(until, now + seconds))
        return until <= now

    def first(self, key):
        """True the first time `key` is seen on this scheduler; used to keep per-piece log lines from flooding."""
        seen = self.__dict__.setdefault("_seen", set())
        if key in seen:
            return False
        seen.add(key)
        return True

    def order(self, sources, piece):
        # Rotate initially to discover useful peers, then prefer measured speed.
        sources = list(dict.fromkeys(sources))
        sources = sources[piece % len(sources):] + sources[:piece % len(sources)]
        now = time.monotonic()
        return sorted(sources, key=lambda s: (self.sources.get(s, (0, 0, 0))[2] > now,
                                             -self.sources.get(s, (0, 0, 0))[0]))
