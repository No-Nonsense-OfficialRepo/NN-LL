"""Fail early when a release uses an unverified interpreter or dependencies."""
import importlib.metadata
from pathlib import Path
import sys

if sys.version_info[:3] != (3, 15, 0) or sys.platform != 'win32':
    raise SystemExit('Release builds require Windows CPython 3.15.0 and build-requirements.lock')
for line in (Path(__file__).resolve().parents[1] / 'build-requirements.lock').read_text().splitlines():
    if not line or line.startswith('#'):
        continue
    name, version = line.split()[0].split('==')
    installed = importlib.metadata.version(name)
    if installed != version:
        raise SystemExit(f'{name}: expected {version}, found {installed}; install build-requirements.lock')
print('Release interpreter and dependency versions verified.')
