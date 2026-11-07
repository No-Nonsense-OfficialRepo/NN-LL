"""Reset launcher state while preserving installed games and the application."""
from pathlib import Path
import os
import shutil
import stat

PREFERENCE_KEYS = frozenset({
    'Appearance/theme', 'Appearance/customColors',
    'Window/resolution', 'Window/hostResolution', 'Window/fillScreen',
})


def reset_preferences(settings):
    settings.sync()
    for key in settings.allKeys():
        if key not in PREFERENCE_KEYS:
            settings.remove(key)
    settings.sync()
    if settings.status() != settings.Status.NoError:
        raise OSError('Could not reset the launcher preferences.')


def reset_data(directory, protected=()):
    """Only delete inside the specified state root; preflight every target.

    Game folders may live inside state, so preserve them and their ancestors.
    Links/junctions fail the preflight before any files are removed.
    """
    root = Path(os.path.abspath(directory))
    protected = [Path(os.path.abspath(p)) for p in protected if p]
    if any(root == p or root.is_relative_to(p) for p in protected):
        raise ValueError('Launcher state overlaps the application or game directory; reset stopped.')
    if not root.exists():
        return
    def check_link(path):
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError(f'Linked state path requires manual review: {path}')
    for path in (root, *root.parents):
        check_link(path)
    targets = []
    def collect(path):
        if not path.is_relative_to(root) or path == root:
            raise ValueError('Unsafe reset target.')
        check_link(path)
        if any(path == p or path.is_relative_to(p) for p in protected):
            return
        if any(p.is_relative_to(path) for p in protected):
            if path.is_dir():
                for child in path.iterdir():
                    collect(child)
            return
        if path.is_dir():
            # Validate descendants before shutil can perform recursive removal.
            for child in path.rglob('*'):
                check_link(child)
        targets.append(path)
    for child in root.iterdir():
        collect(child)
    for path in targets:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
