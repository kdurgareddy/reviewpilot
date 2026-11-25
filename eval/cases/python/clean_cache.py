"""A small TTL cache: clean code with no expected findings."""

import time
from collections import OrderedDict


class TTLCache:
    def __init__(self, maxsize: int = 128, ttl: float = 60.0):
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict[str, tuple[float, object]] = OrderedDict()

    def get(self, key: str, default=None):
        item = self._data.get(key)
        if item is None:
            return default
        expires, value = item
        if expires < time.monotonic():
            del self._data[key]
            return default
        self._data.move_to_end(key)
        return value

    def set(self, key: str, value) -> None:
        self._data[key] = (time.monotonic() + self.ttl, value)
        self._data.move_to_end(key)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)
