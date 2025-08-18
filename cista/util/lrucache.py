from time import monotonic
from typing import Callable


class LRUCache:
    """
    LRUCache is a least-recently-used (LRU) cache with expiry time.

    Attributes:
        open (callable): Function to open a new handle.
        capacity (int): Max number of items in the cache.
        maxage (float): Max age for items in cache in seconds.
        cache (list): Internal list storing the cache items.
    """

    def __init__(self, open: Callable, *, capacity: int, maxage: float):
        """
        Initialize LRUCache.

        Args:
            open (callable): Function to open a new handle.
            capacity (int): Maximum capacity of the cache.
            maxage (float): Max age for items in cache in seconds.
        """
        self.open = open
        self.capacity = capacity
        self.maxage = maxage
        self.cache = []  # Each item is a tuple: (key, handle, timestamp), recent items first

    def __contains__(self, key):
        """Check if key is in cache."""
        return any(rec[0] == key for rec in self.cache)

    def __getitem__(self, key):
        """
        Retrieve an item by its key.

        Args:
            key: The key to retrieve.

        Returns:
            The corresponding item's handle.
        """
        # Take from cache or open a new one
        for i, (k, f, _ts) in enumerate(self.cache):  # noqa: B007
            if k == key:
                self.cache.pop(i)
                break
        else:
            f = self.open(key)
        # Add/restore to end of cache
        self.cache.insert(0, (key, f, monotonic()))
        self.expire_items()
        return f

    def expire_items(self):
        """
        Expire items that are either too old or exceed cache capacity.
        """
        ts = monotonic() - self.maxage
        while len(self.cache) > self.capacity or self.cache and self.cache[-1][2] < ts:
            self.cache.pop()[1].close()

    def close(self):
        """
        Close the cache and remove all items.
        """
        self.capacity = 0
        self.expire_items()
