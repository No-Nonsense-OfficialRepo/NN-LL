import json
import os
import subprocess
import sys

import pytest

from lantool import config_store


def test_nested_settings_preserve_other_writer_changes_and_deletions():
    baseline = {'args': {'a': ['old'], 'b': ['old'], 'remove': True}}
    current = {'args': {'a': ['old'], 'b': ['new'], 'remove': True, 'extra': 1}}
    snapshot = {'args': {'a': ['mine'], 'b': ['old']}}
    result = config_store._merge_changes(current, baseline, snapshot)
    assert result == {'args': {'a': ['mine'], 'b': ['new'], 'extra': 1}}
    assert current['args']['a'] == ['old']


def test_two_processes_merge_changes_and_deletions(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps({'a': 0, 'b': 0, 'obsolete': True}))
    script = '''import sys
from lantool import config_store
path, key = sys.argv[1:]
value = config_store.read(path)
value[key] = 1
if key == 'a': value.pop('obsolete')
print('ready', flush=True)
sys.stdin.readline()
config_store.write(path, value)
'''
    children = [subprocess.Popen([sys.executable, '-B', '-c', script, str(path), key],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True) for key in ('a', 'b')]
    try:
        for child in children:
            assert child.stdout.readline().strip() == 'ready'
        for child in children:
            child.stdin.write('\n')
            child.stdin.flush()
        for child in children:
            out, error = child.communicate(timeout=10)
            assert child.returncode == 0, error
        assert json.loads(path.read_text()) == {'a': 1, 'b': 1}
        assert not list(tmp_path.glob('*.tmp'))
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.wait()


def test_failed_replace_preserves_settings_and_allows_retry(tmp_path, monkeypatch):
    from lantool.filesync import index
    path = tmp_path / 'settings.json'
    path.write_text('{"a": 0}')
    value = config_store.read(path)
    value['a'] = 1
    original = index.replace_file
    def deny(*args):
        raise PermissionError('locked')
    monkeypatch.setattr(index, 'replace_file', deny)
    with pytest.raises(PermissionError):
        config_store.write(path, value)
    assert json.loads(path.read_text()) == {'a': 0}
    monkeypatch.setattr(index, 'replace_file', original)
    config_store.write(path, value)
    assert json.loads(path.read_text()) == {'a': 1}


def test_damaged_settings_are_preserved_when_saving_recovery(tmp_path):
    path = tmp_path / 'settings.json'
    path.write_text('{broken')
    assert config_store.read(path) == {}
    config_store.write(path, {'player_name': 'Player'})
    assert json.loads(path.read_text()) == {'player_name': 'Player'}
    backups = list(tmp_path.glob('settings.json.corrupt-*'))
    assert len(backups) == 1 and backups[0].read_text() == '{broken'
