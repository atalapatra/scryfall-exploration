"""Thread-safe rate limiting.

Scryfall asks clients to space out requests (roughly 10 requests/second for
most endpoints, and stricter limits for some heavier card endpoints).
See https://scryfall.com/docs/api#rate-limits-and-good-citizenship
"""

from __future__ import annotations

import threading
import time
from typing import Callable


class RateLimiter:
    """Makes sure calls with the same key are at least ``interval`` seconds apart.

    Every call waits on the ``"global"`` key. Calls that pass a ``bucket``
    (for example ``"search"``) also wait on that key's own, usually longer, interval.
    """

    def __init__(
        self,
        default_interval: float = 0.1,
        bucket_intervals: dict[str, float] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.default_interval = default_interval
        self.bucket_intervals = dict(bucket_intervals or {})
        self._clock = clock
        self._sleep = sleep
        self._lock = threading.Lock()
        self._next_allowed: dict[str, float] = {}

    def wait(self, bucket: str | None = None) -> None:
        keys = [("global", self.default_interval)]
        if bucket and bucket in self.bucket_intervals:
            keys.append((bucket, self.bucket_intervals[bucket]))

        with self._lock:
            now = self._clock()
            ready_at = max([self._next_allowed.get(k, now) for k, _ in keys] + [now])
            delay = ready_at - now
            # Book the slots now, while holding the lock, so other threads queue behind us.
            for key, interval in keys:
                self._next_allowed[key] = ready_at + interval

        if delay > 0:
            self._sleep(delay)
