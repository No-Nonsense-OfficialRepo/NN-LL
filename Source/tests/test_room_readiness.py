"""Host readiness across transient internet failures, with signed metadata intact."""
import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from lantool.netcore.beacon import make_beacon
from lantool.netcore.discovery import fetch_room_when_ready
from lantool.trust.signing import generate_keypair


async def test_readiness_recovers_after_truncated_tcp_response():
    private, public = generate_keypair()
    body = make_beacon(private, 'abcdef0123456789', '127.0.0.1', 47800,
                       'hash', '1.1', host_pub=public, host_zt='10.147.20.1')
    attempts = 0
    async def serve(reader, writer):
        nonlocal attempts
        attempts += 1
        try:
            await reader.readuntil(b'\r\n\r\n')
            if attempts == 1:
                writer.write(b'HTTP/1.0 200 OK\r\n')
            else:
                writer.write(b'HTTP/1.0 200 OK\r\nContent-Length: ' +
                             str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()
    server = await asyncio.start_server(serve, '127.0.0.1', 0)
    async with server:
        result = await fetch_room_when_ready('127.0.0.1', server.sockets[0].getsockname()[1],
                                             timeout=1, retry_interval=.001)
    assert result['host_pub'] == public
    assert result['net_id'] == 'abcdef0123456789'
    assert attempts == 2


async def test_readiness_deadline_includes_stalled_fetch():
    async def stalled(*args, **kwargs):
        await asyncio.Event().wait()
    started = time.monotonic()
    with patch('lantool.netcore.discovery.fetch_room', new=AsyncMock(side_effect=stalled)):
        with pytest.raises(RuntimeError, match=r'VLA connected.*10\.147\.20\.1:47802') as error:
            await fetch_room_when_ready('10.147.20.1', timeout=.03, retry_interval=.001)
    assert 'TimeoutError' in str(error.value)
    assert time.monotonic() - started < .5


@pytest.mark.parametrize('failure', [ValueError('invalid signed room'),
                                     ValueError('invalid response size')])
async def test_invalid_metadata_is_not_retried(failure):
    with patch('lantool.netcore.discovery.fetch_room', new=AsyncMock(side_effect=failure)) as fetch:
        with pytest.raises(ValueError, match='invalid'):
            await fetch_room_when_ready('10.147.20.1', timeout=1)
    assert fetch.await_count == 1


async def test_readiness_cancellation_stops_pending_attempt():
    started = asyncio.Event()
    async def stalled(*args, **kwargs):
        started.set()
        await asyncio.Event().wait()
    with patch('lantool.netcore.discovery.fetch_room', new=AsyncMock(side_effect=stalled)) as fetch:
        task = asyncio.create_task(fetch_room_when_ready('10.147.20.1'))
        await started.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert fetch.await_count == 1
