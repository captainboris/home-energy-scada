"""Small in-memory duplicate filter; DynamoDB remains the durable authority."""

from collections import OrderedDict


class RecentTimestamps:
    def __init__(self, capacity: int = 50_000):
        self.capacity = capacity
        self._values: OrderedDict[int, None] = OrderedDict()

    def add(self, stamp_ms: int) -> bool:
        """Return True only when the timestamp was not already observed."""
        if stamp_ms in self._values:
            self._values.move_to_end(stamp_ms)
            return False
        self._values[stamp_ms] = None
        while len(self._values) > self.capacity:
            self._values.popitem(last=False)
        return True

    def __len__(self) -> int:
        return len(self._values)

