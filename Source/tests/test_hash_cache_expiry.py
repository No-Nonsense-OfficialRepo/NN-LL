import hashlib
import os
import sqlite3

import pytest

from lantool.filesync import index


@pytest.mark.parametrize('sqlite', [False, True])
def test_expired_cache_rehashes_preserved_timestamp_edit(tmp_path, monkeypatch, sqlite):
    now = [1000000.0]
    monkeypatch.setattr(index.time, 'time', lambda: now[0])
    path = tmp_path / 'data.bin'
    path.write_bytes(b'AAAA')
    cache_path = tmp_path / ('cache.sqlite3' if sqlite else 'cache.json')
    cache = index.SqliteHashCache(cache_path) if sqlite else index.HashCache(cache_path)
    first, _, _ = cache.hashes_with_pieces('data', path)
    stat = path.stat()
    path.write_bytes(b'BBBB')
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert cache.hashes_with_pieces('data', path)[0] == first
    now[0] += index.HASH_CACHE_MAX_AGE + 1
    assert cache.get('data', path.stat()) is None
    assert cache.hashes_with_pieces('data', path)[0] == hashlib.sha256(b'BBBB').hexdigest()
    if sqlite:
        cache.close()


def test_legacy_sqlite_cache_is_migrated_and_rechecked(tmp_path):
    db = tmp_path / 'cache.sqlite3'
    with sqlite3.connect(db) as connection:
        connection.execute('CREATE TABLE files (path TEXT PRIMARY KEY, size INTEGER, mtime_ns INTEGER, sha TEXT, pieces TEXT)')
    cache = index.SqliteHashCache(db)
    path = tmp_path / 'data'
    path.write_bytes(b'hello')
    cache.hashes_with_pieces('data', path)
    assert cache.get('data', path.stat()) == hashlib.sha256(b'hello').hexdigest()
    cache.close()
