"""
utils/cache.py
---------------

Simple in‑process cache with TTL support. This cache is used to
store relatively static API responses such as price system lists or
sales categories. Each entry is stored with an expiry timestamp and
is automatically evicted upon retrieval if expired. The cache is
designed for a single process and is not thread‑safe; however,
FastAPI’s default worker model spawns independent processes so race
conditions are not a concern.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple


class TTLCache:
    """In‑memory cache with time to live (TTL).

    Values are stored with an expiration timestamp. When retrieving
    values, expired entries are pruned. The cache does not enforce
    maximum size; it is cleared only upon expiry or explicit calls
    to :meth:`clear`.
    """

    def __init__(self) -> None:
        self._store: Dict[Any, Tuple[float, Any]] = {}

    def set(self, key: Any, value: Any, ttl: float) -> None:
        """Store a value in the cache for a given number of seconds.

        :param key: cache key (hashable)
        :param value: value to cache
        :param ttl: time to live in seconds
        """
        self._store[key] = (time.time() + ttl, value)

    def get(self, key: Any) -> Any:
        """Retrieve a value from the cache.

        If the entry has expired or does not exist, ``None`` is
        returned and the expired entry is removed.

        :param key: cache key
        :return: cached value or ``None``
        """
        entry = self._store.get(key)
        if not entry:
            return None
        expires_at, value = entry
        if time.time() >= expires_at:
            # expire the entry
            self._store.pop(key, None)
            return None
        return value

    def clear(self) -> None:
        """Clear all entries from the cache."""
        self._store.clear()


# global cache instance
cache = TTLCache()