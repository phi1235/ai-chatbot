from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock

from config.settings import settings

_BUCKETS: dict[str, deque[float]] = defaultdict(deque)
_LOCK = Lock()


def is_allowed(identity: str) -> bool:
    now = time.time()
    window_start = now - 60
    with _LOCK:
        bucket = _BUCKETS[identity]
        while bucket and bucket[0] < window_start:
            bucket.popleft()
        if len(bucket) >= settings.rate_limit_per_minute:
            return False
        bucket.append(now)
        return True
