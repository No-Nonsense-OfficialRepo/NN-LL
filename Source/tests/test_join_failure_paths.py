from lantool._version import __proto__, __version__
"""Per-failure-path checks: every way a join can fail surfaces stage/code/hint.

Covers discovery (fetch_room / fetch_room_when_ready) and the bridge's
room-key join + its finished handler, with the network and VLA faked.
"""
import asyncio
import os
import socket
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

local_qt = Path(__file__).resolve().parents[1] / "build" / "qt-runtime"
if local_qt.is_dir():
    sys.path.insert(0, str(local_qt))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_QUICK_BACKEND", "software")

import lantool.qt  # noqa: F401,E402  (same eager Qt init as production)
from lantool import launcher as core  # noqa: E402
from lantool.netcore import discovery  # noqa: E402
from lantool.netcore.errors import (Code, InvalidBeaconError, JoinError, Stage)  # noqa: E402
from lantool.qt.bridge import LauncherBridge  # noqa: E402


# ---------------------------------------------------------------- discovery

def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve(response: bytes):
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(response)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


async def test_fetch_room_rejects_missing_content_length():
    server, port = await _serve(b"HTTP/1.0 200 OK\r\n\r\n")
    async with server:
        with pytest.raises(InvalidBeaconError) as info:
            await discovery.fetch_room("127.0.0.1", port=port, timeout=2)
    assert (info.value.stage, info.value.code) == (Stage.BEACON, Code.BEACON_INVALID)
    assert info.value.hint


async def test_fetch_room_rejects_oversized_response():
    server, port = await _serve(b"HTTP/1.0 200 OK\r\nContent-Length: 70000\r\n\r\n")
    async with server:
        with pytest.raises(InvalidBeaconError):
            await discovery.fetch_room("127.0.0.1", port=port, timeout=2)


async def test_fetch_room_rejects_unverifiable_body():
    body = b"not a signed beacon"
    server, port = await _serve(
        b"HTTP/1.0 200 OK\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    async with server:
        with patch("lantool.netcore.beacon.parse_beacon", return_value=None):
            with pytest.raises(InvalidBeaconError) as info:
                await discovery.fetch_room("127.0.0.1", port=port, timeout=2)
    assert info.value.code == Code.BEACON_INVALID
    assert isinstance(info.value, ValueError)  # legacy `except ValueError` paths still match


async def test_fetch_room_rejects_non_200_even_with_valid_body():
    body = b"{}"
    server, port = await _serve(
        b"HTTP/1.0 500 Oops\r\nContent-Length: %d\r\n\r\n" % len(body) + body)
    async with server:
        with patch("lantool.netcore.beacon.parse_beacon", return_value={"net_id": "x"}):
            with pytest.raises(InvalidBeaconError):
                await discovery.fetch_room("127.0.0.1", port=port, timeout=2)


async def test_fetch_room_bad_address_is_plain_value_error():
    with pytest.raises(ValueError):
        await discovery.fetch_room("not-an-ip")


async def test_ready_wait_reports_unreachable_with_stage_code_and_cause():
    port = _free_port()  # nothing listens here -> connection refused every attempt
    with pytest.raises(JoinError) as info:
        await discovery.fetch_room_when_ready("127.0.0.1", port=port, timeout=0.4, retry_interval=0.05)
    err = info.value
    assert (err.stage, err.code) == (Stage.BEACON, Code.BEACON_UNREACHABLE)
    assert f"127.0.0.1:{port}" in err.message and err.hint
    assert isinstance(err.__cause__, OSError)


async def test_ready_wait_does_not_retry_invalid_beacon():
    calls = []

    async def bad(address, port=47802, timeout=5):
        calls.append(1)
        raise InvalidBeaconError(Stage.BEACON, Code.BEACON_INVALID, "bad")
    with patch.object(discovery, "fetch_room", bad):
        with pytest.raises(InvalidBeaconError):
            await discovery.fetch_room_when_ready("10.0.0.1", timeout=5, retry_interval=0.01)
    assert len(calls) == 1


async def test_ready_wait_recovers_after_transient_failure():
    attempts = []

    async def flaky(address, port=47802, timeout=5):
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionRefusedError("warming up")
        return {"net_id": "abc"}
    with patch.object(discovery, "fetch_room", flaky):
        beacon = await discovery.fetch_room_when_ready("10.0.0.1", timeout=5, retry_interval=0.01)
    assert beacon == {"net_id": "abc"} and len(attempts) == 3


async def test_ready_wait_rejects_non_positive_timeout():
    with pytest.raises(ValueError):
        await discovery.fetch_room_when_ready("10.0.0.1", timeout=0)


# ------------------------------------------------- bridge: _join_room_key

NET = "a" * 16


class _Tunnel:
    def __init__(self, status):
        self.status = status
        self.left = []

    def begin_join(self, net_id):
        pass

    def wait_connected(self, net_id, timeout):
        self.timeout = timeout
        return self.status

    def _leave_quiet(self, net_id):
        self.left.append(net_id)


def _fake_bridge(status, join_beacon=None):
    statuses = []
    fake = SimpleNamespace(
        role="client", room=None, last_beacon=None,
        tunnel=_Tunnel(status),
        pages={"room": SimpleNamespace(set_status=statuses.append)},
        after=lambda delay, fn, *a: fn(*a),
        _recover_network_session=lambda: None,
        statuses=statuses,
    )

    async def join(beacon):
        if join_beacon:
            await join_beacon(fake, beacon)
    fake._join_beacon_room = join
    return fake


def _run(fake, net_id=NET):
    with patch.object(core, "_other_launcher_running", return_value=False):
        return asyncio.run(LauncherBridge._join_room_key(fake, net_id))


def test_room_key_not_approved_raises_vla_stage_and_leaves_network():
    fake = _fake_bridge(SimpleNamespace(connected=False, message="Waiting for approval", host_ip=""))
    with pytest.raises(JoinError) as info:
        _run(fake)
    assert (info.value.stage, info.value.code) == (Stage.VLA_JOIN, Code.VLA_NOT_CONNECTED)
    assert "approve" in info.value.hint.lower()
    assert fake.tunnel.left == [NET]


def test_room_key_wait_connected_timeout_is_wrapped_as_vla_join():
    fake = _fake_bridge(None)

    def boom(net_id, timeout):
        raise TimeoutError()
    fake.tunnel.wait_connected = boom
    with pytest.raises(JoinError) as info:
        _run(fake)
    assert (info.value.stage, info.value.code) == (Stage.VLA_JOIN, Code.TIMEOUT)
    assert fake.tunnel.left == [NET]


def test_room_key_first_wait_is_capped_at_60s():
    fake = _fake_bridge(SimpleNamespace(connected=False, message="x", host_ip=""))
    with pytest.raises(JoinError):
        _run(fake)
    assert fake.tunnel.timeout <= 60


def test_room_key_unreachable_host_is_beacon_stage():
    ok = SimpleNamespace(connected=True, message="", host_ip="10.9.8.7")
    fake = _fake_bridge(ok)

    async def unreachable(address, port=47802, timeout=60, retry_interval=1):
        raise JoinError(Stage.BEACON, Code.BEACON_UNREACHABLE, "no host", "hint")
    with patch.object(discovery, "fetch_room_when_ready", unreachable):
        with pytest.raises(JoinError) as info:
            _run(fake)
    assert info.value.code == Code.BEACON_UNREACHABLE
    assert fake.tunnel.left == [NET]
    assert any("Waiting for Host room details" in s for s in fake.statuses)


def test_room_key_untyped_metadata_error_gets_beacon_stage():
    ok = SimpleNamespace(connected=True, message="", host_ip="10.9.8.7")
    fake = _fake_bridge(ok)

    async def broken(address, port=47802, timeout=60, retry_interval=1):
        raise OSError("socket exploded")
    with patch.object(discovery, "fetch_room_when_ready", broken):
        with pytest.raises(JoinError) as info:
            _run(fake)
    assert info.value.stage == Stage.BEACON and "socket exploded" in info.value.message
    assert isinstance(info.value.__cause__, OSError)


def test_room_key_mismatch_is_room_key_stage():
    ok = SimpleNamespace(connected=True, message="", host_ip="10.9.8.7")
    fake = _fake_bridge(ok)

    async def other_room(address, port=47802, timeout=60, retry_interval=1):
        return {"net_id": "b" * 16}
    with patch.object(discovery, "fetch_room_when_ready", other_room):
        with pytest.raises(JoinError) as info:
            _run(fake)
    assert (info.value.stage, info.value.code) == (Stage.ROOM_KEY, Code.ROOM_MISMATCH)
    assert fake.tunnel.left == [NET]


def test_room_key_host_setup_incomplete_is_host_setup_stage():
    ok = SimpleNamespace(connected=True, message="", host_ip="10.9.8.7")
    fake = _fake_bridge(ok)  # _join_beacon_room leaves fake.room unset

    async def good(address, port=47802, timeout=60, retry_interval=1):
        return {"net_id": NET, "proto": __proto__, "version": __version__}
    with patch.object(discovery, "fetch_room_when_ready", good):
        with pytest.raises(JoinError) as info:
            _run(fake)
    assert (info.value.stage, info.value.code) == (Stage.HOST_SETUP, Code.HOST_SETUP)
    assert fake.last_beacon["host"] == "10.9.8.7"


def test_room_key_success_does_not_leave_network():
    ok = SimpleNamespace(connected=True, message="", host_ip="10.9.8.7")

    async def finish(fake_self, beacon):
        fake_self.room = object()
    fake = _fake_bridge(ok, join_beacon=finish)

    async def good(address, port=47802, timeout=60, retry_interval=1):
        return {"net_id": NET, "proto": __proto__, "version": __version__}
    with patch.object(discovery, "fetch_room_when_ready", good):
        _run(fake)
    assert fake.tunnel.left == []


def test_room_key_failure_keeps_network_when_other_launcher_running():
    fake = _fake_bridge(SimpleNamespace(connected=False, message="x", host_ip=""))
    with patch.object(core, "_other_launcher_running", return_value=True):
        with pytest.raises(JoinError):
            asyncio.run(LauncherBridge._join_room_key(fake, NET))
    assert fake.tunnel.left == []


# --------------------------------------- bridge: _room_key_finished dialog

def _finished_fake():
    messages = []
    fake = SimpleNamespace(
        busy=True, _beacon_joining=True, _status="",
        ui_message=lambda *a, **k: messages.append((a, k)),
        publish=lambda: None, messages=messages)
    return fake


class _Done:
    def __init__(self, exc=None):
        self.exc = exc

    def result(self):
        if self.exc:
            raise self.exc


def test_finished_failure_passes_stage_code_hint_to_dialog():
    fake = _finished_fake()
    err = JoinError(Stage.BEACON, Code.BEACON_UNREACHABLE, "no host", "keep room open")
    with patch.object(core.LauncherCore, "_log_room_error"):
        LauncherBridge._room_key_finished(fake, _Done(err))
    assert fake.busy is False and fake._beacon_joining is False
    (args, kwargs), = fake.messages
    assert args == ("showerror", "Room key join failed", "no host")
    assert kwargs == {"stage": "beacon", "code": Code.BEACON_UNREACHABLE, "hint": "keep room open"}
    assert fake._status == "Could not join the room: no host"


def test_finished_failure_with_untyped_error_still_has_a_code():
    fake = _finished_fake()
    with patch.object(core.LauncherCore, "_log_room_error"):
        LauncherBridge._room_key_finished(fake, _Done(RuntimeError("weird")))
    (_, kwargs), = fake.messages
    assert kwargs["stage"] == "unknown" and kwargs["code"] == Code.UNKNOWN


def test_finished_success_shows_no_dialog():
    fake = _finished_fake()
    LauncherBridge._room_key_finished(fake, _Done())
    assert fake.messages == [] and fake.busy is False


# ---------------------------------- bridge.ui_message carries error details

def test_ui_message_accepts_join_error_object_directly():
    fake = SimpleNamespace(_dialog={}, _events=[], publish=lambda: None)
    err = JoinError(Stage.PLANET, Code.PLANET_FETCH, "no planet", "retry")
    LauncherBridge.ui_message(fake, "showerror", "T", err)
    assert fake._dialog == {"title": "T", "message": "no planet", "error": True,
                            "stage": "planet", "code": Code.PLANET_FETCH, "hint": "retry"}
    assert fake._events[0]["code"] == Code.PLANET_FETCH


def test_ui_message_without_details_has_empty_detail_fields():
    fake = SimpleNamespace(_dialog={}, _events=[], publish=lambda: None)
    LauncherBridge.ui_message(fake, "showinfo", "T", "hello")
    assert fake._dialog["error"] is False
    assert (fake._dialog["stage"], fake._dialog["code"], fake._dialog["hint"]) == ("", "", "")
