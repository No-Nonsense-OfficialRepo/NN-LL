"""Test setup shared by all tests.

Python 3.15 + PySide6 6.12: importing PySide6 leaves concurrent.futures' lazy
names unresolved, which breaks asyncio.to_thread / run_in_executor in every test
that runs afterwards. Resolve them before any test module imports PySide6.
"""
import concurrent.futures as _cf
import os

# Exercise the current QML source, rather than a previous desktop session's
# compiled disk cache (which can survive same-size edits on Windows).
os.environ['QML_DISABLE_DISK_CACHE'] = '1'

for _name in ('ThreadPoolExecutor', 'ProcessPoolExecutor'):
    getattr(_cf, _name)
