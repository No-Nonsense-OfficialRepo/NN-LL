"""Real socket transfers stop while paused and resume verified partial files."""
import asyncio
import hashlib
from urllib.parse import unquote

import pytest

from lantool.filesync.client import sync_game
from lantool.filesync.control import TransferControl
from lantool.filesync.index import PART_SUFFIX, build_index
from lantool.filesync.server import FileSyncServer, _RANGE_RE, _status
from lantool.trust.signing import generate_keypair, sign_obj


@pytest.mark.parametrize('pieces', [True, False])
async def test_pause_closes_downloads_and_resumes_saved_progress(tmp_path, pieces):
    priv, pub = generate_keypair()
    game = tmp_path/'host'/'game'
    game.mkdir(parents=True)
    payload = bytes(range(256)) * (12*1024*1024//256)
    (game/'game.exe').write_bytes(payload)

    gate = asyncio.Event()  # Holds the server at 1 MiB until the test has seen the pause.
    class SlowHost(FileSyncServer):
        async def signed_index(self, gid):
            index = build_index(gid, game)
            if not pieces:
                for entry in index['files']:
                    entry.pop('pieces',None)
            return sign_obj(priv,index)

        async def _file(self, writer, rest, range_header, *, keep_alive=False):
            match = _RANGE_RE.match(range_header or '')
            start = int(match[1]) if match else 0
            end = int(match[2]) if match and match[2] else len(payload)-1
            length = end-start+1
            self.requests.append((unquote(rest),start,length))
            writer.write(_status(206 if match else 200)+f'Content-Length: {length}\r\n\r\n'.encode())
            for offset in range(start,end+1,16384):
                (await gate.wait() if offset >= start+1024*1024 and not gate.is_set() else None); writer.write(payload[offset:min(offset+16384,end+1)])
                await writer.drain()
                # Delay only until the pause has been observed. Windows may
                # round 2 ms sleeps up to a timer tick; delaying every resumed
                # 16 KiB block can exceed the test's 10-second deadline.
                await asyncio.sleep(0 if gate.is_set() else .002)

    server = SlowHost(priv,tmp_path/'host',host='127.0.0.1',port=0)
    await server.start()
    paused = asyncio.Event()
    states = []
    def state(value):
        states.append(value)
        if value == 'paused':
            paused.set()
    control = TransferControl(state)
    updates = []
    requested = False
    def progress(done,total,path):
        nonlocal requested
        updates.append((done,total,path))
        if done >= 1024*1024 and not requested:
            requested = True
            control.pause()
    task = asyncio.create_task(sync_game('127.0.0.1',server.port,pub,'game',
        tmp_path/'client',progress=progress,control=control,concurrency=2))
    try:
        await asyncio.wait_for(paused.wait(),5)
        assert not task.done()
        partial = tmp_path/'client'/('game.exe'+PART_SUFFIX)
        assert partial.exists(), sorted(p.name for p in partial.parent.iterdir())
        assert not (tmp_path/'client'/'game.exe').exists()
        count,position = len(server.requests),list(updates)
        await asyncio.sleep(.15)
        assert len(server.requests) == count
        assert updates == position
        gate.set(); control.resume()
        result = await asyncio.wait_for(task,10)
        assert result.ok, result.error
        assert hashlib.sha256((tmp_path/'client'/'game.exe').read_bytes()).digest() == hashlib.sha256(payload).digest()
        assert not partial.exists()
        assert any(start > 0 for _,start,_ in server.requests[count:])
        assert updates[-1][:2] == (len(payload),len(payload))
        assert states.count('paused') == 1
        # AUDIT-5: the total never shrinks to the remaining work, and done keeps counting up after resume.
        assert {total for _,total,_ in updates} == {len(payload)}
        after = [done for done,_,_ in updates[len(position):]]
        assert after and after[0] > 0
        assert after == sorted(after)
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task,return_exceptions=True)
        gate.set(); await server.stop()


async def test_pause_before_start_makes_no_requests_and_cancel_cleans_up():
    states,started = [],[]
    control = TransferControl(states.append)
    control.pause()
    async def operation():
        started.append(True)
        await asyncio.sleep(10)
    task = asyncio.create_task(control.run(operation))
    await asyncio.sleep(.02)
    assert states[-1] == 'paused'
    assert not started
    control.resume()
    await asyncio.sleep(.02)
    assert started == [True]
    task.cancel()
    await asyncio.gather(task,return_exceptions=True)
    assert task.cancelled()
