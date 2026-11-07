"""Optional timeout overrides from <app data>/timeouts.json.

Each value falls back to its default when the file is missing, unreadable, not a
number, or outside its allowed range. Nothing changes unless someone sets a value,
so a bad file can never stop the launcher from starting.
"""
import json
from pathlib import Path

# name: (default seconds, minimum, maximum)
LIMITS = {
    'network_wait': (30.0, 10.0, 120.0),     # wait for the room network to connect
    'close_deadline': (25.0, 5.0, 120.0),    # total time allowed for shutdown
    'shutdown_step': (5.0, 1.0, 60.0),       # each shutdown step
    'cleanup_step': (15.0, 5.0, 120.0),      # tunnel cleanup step
}


def load(app_dir) -> dict:
    values = {name: default for name, (default, _lo, _hi) in LIMITS.items()}
    try:
        data = json.loads((Path(app_dir) / 'timeouts.json').read_text(encoding='utf-8'))
    except Exception:
        return values
    if not isinstance(data, dict):
        return values
    for name, (_default, low, high) in LIMITS.items():
        value = data.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high:
            values[name] = float(value)
    return values
