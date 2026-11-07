import json
from lantool import timeouts


def test_defaults_when_no_file(tmp_path):
    values = timeouts.load(tmp_path)
    assert values == {'network_wait': 30.0, 'close_deadline': 25.0,
                      'shutdown_step': 5.0, 'cleanup_step': 15.0}


def test_valid_override_applies_and_bad_values_fall_back(tmp_path):
    (tmp_path / 'timeouts.json').write_text(json.dumps(
        {'network_wait': 60, 'close_deadline': 9999, 'shutdown_step': True, 'cleanup_step': 'x'}),
        encoding='utf-8')
    values = timeouts.load(tmp_path)
    assert values['network_wait'] == 60.0          # valid, applied
    assert values['close_deadline'] == 25.0        # above maximum, default
    assert values['shutdown_step'] == 5.0          # bool rejected, default
    assert values['cleanup_step'] == 15.0          # not a number, default


def test_unreadable_file_falls_back(tmp_path):
    (tmp_path / 'timeouts.json').write_text('{not json', encoding='utf-8')
    assert timeouts.load(tmp_path)['network_wait'] == 30.0
