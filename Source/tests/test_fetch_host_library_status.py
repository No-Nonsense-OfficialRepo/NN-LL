"""_fetch_host_library rejects non-200 responses and always waits for the connection to close (audit A16)."""
import asyncio
import os
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


async def _serve(response: bytes):
    async def handle(reader, writer):
        await reader.readuntil(b"\r\n\r\n")
        writer.write(response)
        await writer.drain()
        writer.close()
    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    return server, server.sockets[0].getsockname()[1]


def _fetch(port):
    return core.LauncherCore._fetch_host_library(SimpleNamespace(), "127.0.0.1", port, "host-key")


def test_500_response_raises_a_clear_error():
    async def run():
        body = b'{"error": "boom"}'
        server, port = await _serve(b"HTTP/1.0 500 Internal Server Error\r\nContent-Length: %d\r\n\r\n%s" % (len(body), body))
        try:
            await _fetch(port)
        finally:
            server.close()
            await server.wait_closed()
    with pytest.raises(RuntimeError, match="500 Internal Server Error"):
        asyncio.run(run())


def test_missing_status_line_raises():
    async def run():
        server, port = await _serve(b"garbage\r\nContent-Length: 2\r\n\r\n{}")
        try:
            await _fetch(port)
        finally:
            server.close()
            await server.wait_closed()
    with pytest.raises(RuntimeError, match="request failed"):
        asyncio.run(run())


def test_close_waits_for_wait_closed_but_not_forever():
    events = []

    class Writer:
        def write(self, data):
            events.append('write')

        async def drain(self):
            pass

        def close(self):
            events.append('close')

        async def wait_closed(self):
            events.append('wait_closed')
            await asyncio.sleep(60)

    class Reader:
        async def readuntil(self, separator):
            return b"HTTP/1.0 500 Oops\r\nContent-Length: 2\r\n\r\n"

    async def fake_open(host, port):
        return Reader(), Writer()

    real_wait_for = asyncio.wait_for

    async def quick_wait_for(awaitable, timeout):
        return await real_wait_for(awaitable, min(timeout, 0.1))

    async def run():
        with patch.object(core.asyncio, 'open_connection', fake_open), patch.object(core.asyncio, 'wait_for', quick_wait_for):
            await _fetch(0)

    with pytest.raises(RuntimeError, match="500 Oops"):
        asyncio.run(run())
    assert events == ['write', 'close', 'wait_closed']
