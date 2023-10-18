from time import sleep
from unittest.mock import Mock

import pytest

from cista.lrucache import LRUCache  # Replace with actual import


def mock_open(key):
    mock = Mock()
    mock.close = Mock()
    mock.content = f"content-{key}"
    return mock

def test_contains():
    cache = LRUCache(open=mock_open, capacity=2, maxage=10)
    assert "key1" not in cache
    cache["key1"]
    assert "key1" in cache

def test_getitem():
    cache = LRUCache(open=mock_open, capacity=2, maxage=10)
    assert cache["key1"].content == "content-key1"

def test_capacity():
    cache = LRUCache(open=mock_open, capacity=2, maxage=10)
    item1 = cache["key1"]
    item2 = cache["key2"]
    cache["key3"]
    assert "key1" not in cache
    item1.close.assert_called()

def test_expiry():
    cache = LRUCache(open=mock_open, capacity=2, maxage=0.1)
    item = cache["key1"]
    sleep(0.2)  # Wait for expiration
    cache.expire_items()
    assert "key1" not in cache
    item.close.assert_called()

def test_close():
    cache = LRUCache(open=mock_open, capacity=2, maxage=10)
    item = cache["key1"]
    cache.close()
    assert "key1" not in cache
    item.close.assert_called()

def test_lru_mechanism():
    cache = LRUCache(open=mock_open, capacity=2, maxage=10)
    item1 = cache["key1"]
    item2 = cache["key2"]
    cache["key1"]  # Make key1 recently used
    cache["key3"]  # This should remove key2
    assert "key1" in cache
    assert "key2" not in cache
    assert "key3" in cache
    item2.close.assert_called()
    item1.close.assert_not_called()
