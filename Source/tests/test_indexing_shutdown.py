"""Closing during indexing must release actual disk workers and HTTP clients."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock, Mock

from lantool.filesync import index
from lantool.filesync.server import FileSyncServer
from lantool.trust.signing import generate_keypair


class SlowReader:
    def __init__(self, stream, entered):
        self.stream, self.entered = stream, entered
        self.closed = False

    def __enter__(self):
        self.stream.__enter__()
        return self

    def __exit__(self, *args):
        result = self.stream.__exit__(*args)
        self.closed = True
        return result

    def read(self, size):
        self.entered.set()
        time.sleep(.06)
        return self.stream.read(size)

    def fileno(self):
        return self.stream.fileno()


async def entered(event):
    deadline = asyncio.get_running_loop().time() + 2
    while not event.is_set():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError('Hash worker never entered its file read')
        await asyncio.sleep(.005)


class IndexingShutdownTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_index_waits_for_worker_file_to_close(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'large.bin').write_bytes(b'a' * (8 * index.CHUNK))
            started, readers = threading.Event(), []
            original_open = open
            def slow_open(*args, **kwargs):
                reader = SlowReader(original_open(*args, **kwargs), started)
                readers.append(reader)
                return reader
            cache = index.HashCache()
            with patch.object(index, 'open', slow_open, create=True):
                task = asyncio.create_task(index.run_hash_work(index.build_index, 'game', root, cache))
                await entered(started)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            self.assertTrue(readers)
            self.assertTrue(all(reader.closed for reader in readers))
            self.assertEqual(cache._d, {}, 'Cancelled file must not publish partial hashes')
            (root / 'large.bin').rename(root / 'released.bin')

    async def test_stop_server_during_http_index_closes_hash_and_connection(self):
        private, _public = generate_keypair()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / 'game'; game.mkdir()
            (game / 'large.bin').write_bytes(b'a' * (8 * index.CHUNK))
            started, readers = threading.Event(), []
            original_open = open
            def slow_open(*args, **kwargs):
                reader = SlowReader(original_open(*args, **kwargs), started)
                readers.append(reader)
                return reader
            server = FileSyncServer(private, root, host='127.0.0.1', port=0)
            await server.start()
            reader, writer = await asyncio.open_connection('127.0.0.1', server.port)
            try:
                with patch.object(index, 'open', slow_open, create=True):
                    writer.write(b'GET /index/game HTTP/1.0\r\n\r\n')
                    await writer.drain()
                    await entered(started)
                    await asyncio.wait_for(server.stop(), 1)
                self.assertEqual(await asyncio.wait_for(reader.read(), 1), b'')
                self.assertFalse(server._handlers)
                self.assertFalse(server._writers)
                self.assertTrue(readers and all(item.closed for item in readers))
                (game / 'large.bin').rename(game / 'released.bin')
            finally:
                writer.close()
                await writer.wait_closed()
                await server.stop()

    async def test_cancel_client_diff_stops_hashing_existing_files(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'large.bin'; path.write_bytes(b'a' * (8 * index.CHUNK))
            started, readers = threading.Event(), []
            original_open = open
            def slow_open(*args, **kwargs):
                reader = SlowReader(original_open(*args, **kwargs), started)
                readers.append(reader)
                return reader
            files = [{'path':'large.bin', 'size':path.stat().st_size, 'sha256':'0' * 64}]
            with patch.object(index, 'open', slow_open, create=True):
                task = asyncio.create_task(index.run_hash_work(index.diff_index, files, root, index.HashCache()))
                await entered(started)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            self.assertTrue(readers and all(item.closed for item in readers))

    async def test_background_peer_verification_cancellation_releases_file(self):
        from lantool.launcher import LauncherCore
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            path = root / 'large.bin';path.write_bytes(b'a' * (8 * index.CHUNK))
            files = [{'path':'large.bin', 'size':path.stat().st_size, 'sha256':'0' * 64}]
            started, readers = threading.Event(), []
            original_open = open
            def slow_open(*args, **kwargs):
                reader = SlowReader(original_open(*args, **kwargs), started)
                readers.append(reader)
                return reader
            peer = Mock()
            app = SimpleNamespace(library={'game':{'id':'game','install_dir':str(root)}},
                                  syncing_game=False, peer_file_server=peer,
                                  seeded_files={}, seeded_games=set(), presence_client=None,
                                  trusted_host_pub='fixture', room=SimpleNamespace(network_id='net1'))
            with patch('lantool.filesync.client.fetch_index', new=AsyncMock(return_value=files)), \
                 patch.object(index, 'open', slow_open, create=True):
                task = asyncio.create_task(LauncherCore._seed_existing_games(
                    app, {'host_zt':'127.0.0.1', 'sync_port':1, 'host_pub':'fixture', 'net_id':'net1'}))
                await entered(started)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await asyncio.wait_for(task, 1)
            self.assertTrue(readers and all(item.closed for item in readers))
            self.assertEqual(app.seeded_games, set())
            peer.register_index.assert_not_called()
            path.rename(root / 'released.bin')


class IndexingProcessExitTests(unittest.TestCase):
    def test_runtime_process_exits_after_cancelled_disk_worker(self):
        # Run in a disposable process: an orphaned non-daemon executor thread
        # would keep Python alive even after its asyncio/UI thread exits.
        script = '''
import threading, time
from pathlib import Path
from lantool.launcher import AsyncLoopThread
from lantool.filesync.index import run_hash_work, check_cancelled
started=threading.Event()
path=Path('indexing-open-file.bin');path.write_bytes(b'test')
def index_file(*,cancelled):
    with path.open('rb') as stream:
        started.set()
        for n in range(500):
            check_cancelled(cancelled)
            time.sleep(.02)
runtime=AsyncLoopThread()
future=runtime.submit(run_hash_work(index_file))
assert started.wait(2)
runtime.stop()
assert not runtime.thread.is_alive()
path.rename('released-file.bin')
print('exited cleanly')
'''
        with tempfile.TemporaryDirectory() as folder:
            env = dict(os.environ)
            env['PYTHONPATH'] = os.pathsep.join(str(Path(p).resolve()) for p in sys.path if p)
            result = subprocess.run([sys.executable, '-c', script], cwd=folder,
                                    env=env, capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('exited cleanly', result.stdout)
