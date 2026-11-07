"""Portable installation receipt. Hash the executable once, reuse its file stamp."""
import hashlib
import json
import os
import uuid
from .filesync.index import replace_file
from pathlib import Path

NAME = '.lantool-install.json'


def mark_shared_installed(folder, game_id):
    root = Path(folder)
    receipt = root / (NAME + '.shared')
    temp = root / (NAME + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps({'version': 1, 'game_id': game_id}), encoding='utf-8')
        replace_file(temp, receipt)
    finally:
        temp.unlink(missing_ok=True)


def shared_matches(folder, game_id):
    try:
        saved = json.loads((Path(folder) / (NAME + '.shared')).read_text(encoding='utf-8'))
        return saved.get('version') == 1 and saved.get('game_id') == game_id
    except (OSError, ValueError, AttributeError):
        return False


def executable_record(folder, relative, *, cancelled=None):
    from .filesync.index import check_cancelled
    check_cancelled(cancelled)
    root = Path(folder).resolve()
    relative = relative.replace('\\', '/')
    exe = (root / relative).resolve()
    if root not in exe.parents or not exe.is_file():
        raise ValueError('Game executable is missing or outside its installation.')
    stat = exe.stat()
    stamp = [stat.st_size, stat.st_mtime_ns]
    try:
        saved = json.loads((root / NAME).read_text(encoding='utf-8'))
        if (saved.get('version') == 1 and saved.get('exe', '').casefold() == relative.casefold()
                and saved.get('stamp') == stamp and saved.get('ctime_ns') == stat.st_ctime_ns
                and isinstance(saved.get('sha256'), str) and len(saved['sha256']) == 64):
            return saved
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    digest = hashlib.sha256()
    with exe.open('rb') as stream:
        while True:
            check_cancelled(cancelled)
            block = stream.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    after = exe.stat()
    if (after.st_size, after.st_mtime_ns, after.st_ctime_ns) != (stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns):
        raise ValueError('The executable changed during verification. Retry when copying finishes.')
    record = {'version': 1, 'exe': relative, 'stamp': stamp,
              'ctime_ns': stat.st_ctime_ns, 'sha256': digest.hexdigest()}
    temp = root / (NAME + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps(record), encoding='utf-8')
        replace_file(temp, root / NAME)
    except OSError:
        pass  # Read-only games can still launch; their hash cannot be cached here.
    finally:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
    return record


PENDING = '.lantool-pending'


def mark_pending(folder, game_id):
    """Written when a sync starts. Removed only when the sync finishes with every file verified."""
    root = Path(folder)
    root.mkdir(parents=True, exist_ok=True)
    temp = root / (PENDING + '.' + uuid.uuid4().hex + '.tmp')
    try:
        temp.write_text(json.dumps({'version': 1, 'game_id': game_id}), encoding='utf-8')
        replace_file(temp, root / PENDING)
    finally:
        temp.unlink(missing_ok=True)


def clear_pending(folder):
    if folder:
        try:
            (Path(folder) / PENDING).unlink(missing_ok=True)
        except OSError:
            pass


def is_pending(folder):
    return bool(folder) and (Path(folder) / PENDING).exists()


def matches(folder, manifest, *, cancelled=None):
    expected = manifest.get('exe_sha256')
    if not expected:
        return False
    try:
        return executable_record(folder, manifest['exe'], cancelled=cancelled)['sha256'] == expected
    except (OSError, ValueError, KeyError):
        return False
