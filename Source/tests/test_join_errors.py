import asyncio
from types import SimpleNamespace

import pytest

from lantool.netcore.controller import RoomController, State
from lantool.netcore.errors import (Code, InvalidBeaconError, JoinError, Stage,
                                    as_join_error)
from lantool.ui.dialogs import Messages


def test_join_error_is_runtime_error_with_message_as_str():
    err = JoinError(Stage.ADDRESS, Code.NO_ADDRESS, 'no ip', 'try again')
    assert isinstance(err, RuntimeError)
    assert str(err) == 'no ip'
    assert err.to_dict() == {'stage': 'address', 'code': 'E_NO_ADDRESS',
                             'message': 'no ip', 'hint': 'try again'}


def test_invalid_beacon_error_is_also_value_error():
    err = InvalidBeaconError(Stage.BEACON, Code.BEACON_INVALID, 'bad')
    assert isinstance(err, ValueError) and isinstance(err, JoinError)


def test_as_join_error_keeps_typed_and_wraps_others():
    typed = JoinError(Stage.BEACON, Code.BEACON_UNREACHABLE, 'x')
    assert as_join_error(typed, Stage.UNKNOWN) is typed
    cause = OSError('boom')
    wrapped = as_join_error(cause, Stage.VLA_JOIN, Code.VLA_JOIN)
    assert (wrapped.stage, wrapped.code, str(wrapped)) == (Stage.VLA_JOIN, Code.VLA_JOIN, 'boom')
    assert wrapped.__cause__ is cause


def test_as_join_error_maps_timeout_and_empty_messages():
    timed = as_join_error(TimeoutError(), Stage.BEACON)
    assert timed.code == Code.TIMEOUT and 'timed out' in timed.message
    assert 'RuntimeError' in as_join_error(RuntimeError(), Stage.UNKNOWN).message


def test_messages_forwards_detail_only_when_given():
    calls = []
    parent = SimpleNamespace(ui_message=lambda *a, **k: calls.append((a, k)))
    Messages().showerror('T', 'M', parent=parent)
    Messages().showerror('T', 'M', parent=parent, stage='beacon', code='E_X', hint='h')
    assert calls[0] == (('showerror', 'T', 'M'), {})
    assert calls[1] == (('showerror', 'T', 'M'), {'stage': 'beacon', 'code': 'E_X', 'hint': 'h'})


class _ZT:
    last_error = ''

    def __init__(self, ip):
        self.ip = ip

    async def join(self, net_id):
        pass

    async def wait_ip(self, net_id):
        return self.ip

    async def leave(self, net_id):
        pass

    def alias(self, net_id):
        return 'zt'


async def test_controller_reports_typed_error_when_no_ip():
    adapter = SimpleNamespace(restore=lambda: None)
    ctl = RoomController(_ZT(None), adapter, SimpleNamespace(), lambda: '', None, lambda b: '10.0.0.1')
    await ctl.on_beacon({'net_id': 'abc'})
    assert ctl.state == State.ETHERNET
    assert isinstance(ctl.join_error, JoinError)
    assert (ctl.join_error.stage, ctl.join_error.code) == (Stage.ADDRESS, Code.NO_ADDRESS)
    assert ctl.error == str(ctl.join_error)


async def test_controller_planet_failure_is_typed():
    async def refuse(_b):
        return False
    adapter = SimpleNamespace(restore=lambda: None)
    ctl = RoomController(_ZT('10.0.0.2'), adapter, SimpleNamespace(), lambda: 'old', refuse, lambda b: '10.0.0.1')
    await ctl.on_beacon({'net_id': 'abc', 'moon_id': 'm', 'planet_hash': 'new'})
    assert ctl.join_error.stage == Stage.PLANET and ctl.join_error.code == Code.PLANET_FETCH

# --- timing_log records stage + code on failure ---

def test_timing_failure_includes_stage_and_code_for_typed_errors():
    from lantool.netcore import timing_log
    err = JoinError(Stage.ADDRESS, Code.NO_ADDRESS, 'no ip')
    assert timing_log.failure(err) == 'JoinError stage=address code=E_NO_ADDRESS'
    assert timing_log.failure(err, 'vla:') == 'vla:JoinError stage=address code=E_NO_ADDRESS'


def test_timing_failure_for_untyped_errors_is_just_the_type_name():
    from lantool.netcore import timing_log
    assert timing_log.failure(OSError('x')) == 'OSError'


def test_timing_failure_handles_subclass_with_stage_enum():
    from lantool.netcore import timing_log
    err = InvalidBeaconError(Stage.BEACON, Code.BEACON_INVALID, 'bad')
    assert timing_log.failure(err) == 'InvalidBeaconError stage=beacon code=E_BEACON_INVALID'
