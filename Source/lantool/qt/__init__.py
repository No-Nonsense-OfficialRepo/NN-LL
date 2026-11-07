"""Qt Quick desktop frontend."""
import os

# Resolve Qt types eagerly before room callbacks reach worker threads. A
# Shiboken lazy_import placeholder is not callable from those callbacks.
os.environ['PYSIDE6_OPTION_LAZY'] = '0'

# Python 3.15 + PySide6 6.12: importing PySide6 leaves the lazy names of
# concurrent.futures unresolved, so asyncio's default executor later fails with
# "'lazy_import' object is not callable". Touch them first (before PySide6 is
# imported) so they are resolved and cached in the module.
import concurrent.futures as _cf
for _name in ('ThreadPoolExecutor', 'ProcessPoolExecutor'):
    getattr(_cf, _name)
del _cf, _name
