"""Reset destructive behavior against disposable folders only."""
from pathlib import Path
from unittest.mock import Mock, patch
from types import SimpleNamespace
import stat
import pytest
from lantool.reset_data import reset_data, reset_preferences, PREFERENCE_KEYS


def test_reset_removes_profiles_keys_logs_and_caches_but_keeps_nested_games(tmp_path):
    state = tmp_path / 'LanTool'
    games = state / 'downloads' / 'My Game'
    games.mkdir(parents=True)
    (games / 'game.exe').write_bytes(b'game')
    (state / 'downloads' / 'cache.json').write_text('cache')
    (state / 'profile').mkdir()
    (state / 'profile/avatar.png').write_bytes(b'avatar')
    for name in ('launcher.json', 'host_identity.json', 'room-errors.log', 'file_hash_cache.json'):
        (state / name).write_text('state')
    external = tmp_path / 'Other Game'
    external.mkdir()
    (external / 'game.exe').write_bytes(b'external')
    reset_data(state, [games, external])
    assert sorted(str(p.relative_to(state)) for p in state.rglob('*')) == [
        'downloads', str(Path('downloads/My Game')), str(Path('downloads/My Game/game.exe'))]
    assert (games / 'game.exe').read_bytes() == b'game'
    assert (external / 'game.exe').read_bytes() == b'external'


def test_reset_refuses_application_or_game_root_overlap(tmp_path):
    app = tmp_path / 'App'
    state = app / 'data'
    state.mkdir(parents=True)
    (state / 'keep').touch()
    with pytest.raises(ValueError):
        reset_data(state, [app])
    assert (state / 'keep').exists()


def test_reset_preflight_refuses_link_before_deleting_anything(tmp_path):
    state = tmp_path / 'state'
    state.mkdir()
    (state / 'first.txt').touch()
    target = tmp_path / 'game'
    target.mkdir()
    linked = state / 'linked'
    linked.mkdir()
    original = Path.lstat
    def attributes(path, *args, **kwargs):
        if path == linked:
            return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        return original(path, *args, **kwargs)
    with patch.object(Path, 'lstat', attributes), pytest.raises(ValueError):
        reset_data(state)
    assert (state / 'first.txt').exists()
    assert target.exists()


def test_reset_preferences_preserves_only_theme_and_resolution_keys():
    settings = Mock()
    settings.allKeys.return_value = list(PREFERENCE_KEYS) + ['Player/name', 'Window/oldKey', 'Appearance/unknown', 'Network/room']
    settings.status.return_value = settings.Status.NoError
    reset_preferences(settings)
    assert {c.args[0] for c in settings.remove.call_args_list} == {'Player/name', 'Window/oldKey', 'Appearance/unknown', 'Network/room'}


def test_saved_preferences_remain_exactly_intact(tmp_path):
    import lantool.qt
    from PySide6.QtCore import QSettings
    settings = QSettings(str(tmp_path / 'settings.ini'), QSettings.IniFormat)
    values = {'Appearance/theme': 'Custom', 'Appearance/customColors': '{"brass":"#123456"}',
              'Window/resolution': '1920x1080', 'Window/hostResolution': '1080', 'Window/fillScreen': True}
    for key, value in values.items():
        settings.setValue(key, value)
    settings.setValue('Player/name', 'Reset me')
    reset_preferences(settings)
    assert set(settings.allKeys()) == PREFERENCE_KEYS
    assert {key: settings.value(key) for key in values} == values
