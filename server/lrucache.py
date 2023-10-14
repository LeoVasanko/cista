from time import monotonic

class LRUCache:
    def __init__(self, open: callable, *, capacity: int, maxage: float):
        self.open = open
        self.capacity = capacity
        self.maxage = maxage
        self.cache = []  # Each item is a tuple: (key, handle, timestamp), recent items first

    def __contains__(self, key):
        return any(rec[0] == key for rec in self.cache)

    def __getitem__(self, key):
        # Take from cache or open a new one
        for i, (k, f, ts) in enumerate(self.cache):
            if k == key:
                self.cache.pop(i)
                break
        else:
            f = self.open(key)
        # Add/restore to end of cache
        self.cache.append((key, f, monotonic()))
        self.expire_items()
        return f

    def expire_items(self):
        ts = monotonic() - self.maxage
        while len(self.cache) > self.capacity or self.cache and self.cache[-1][2] < ts:
            self.cache.pop()[1].close()
