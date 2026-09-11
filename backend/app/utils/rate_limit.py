"""Tiny in-memory sliding-window rate limiter for public ingest endpoints.

Per-key buckets of hit timestamps; no storage, no config service. Scooped for
single-process use (tests reset via `reset()`). Thread-safety is best-effort
(dict ops under the GIL); correctness failure only over/under-admits slightly.
"""
from __future__ import annotations

import time

_buckets: dict[str, list[float]] = {}


def allow(key: str, *, limit: int, window_sec: int,
          now: float | None = None) -> tuple[bool, int]:
    """Record a hit. Returns (allowed, retry_after_sec)."""
    now = time.monotonic() if now is None else now
    bucket = _buckets.setdefault(key, [])
    cutoff = now - window_sec
    while bucket and bucket[0] <= cutoff:
        bucket.pop(0)
    if len(bucket) >= limit:
        retry = int(bucket[0] + window_sec - now) + 1
        return False, max(1, retry)
    bucket.append(now)
    return True, 0


def reset() -> None:
    _buckets.clear()
