import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType
from unittest.mock import AsyncMock, patch

from lantool.launcher import LauncherCore
from lantool.trust.signing import generate_keypair, sign_obj


class LibraryLoadingTests(unittest.IsolatedAsyncioTestCase):
    async def test_host_parameter_edits_reach_client_in_signed_library(self):
        from lantool.filesync.server import FileSyncServer
        private,public=generate_keypair()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            game=root/'host'/'game';game.mkdir(parents=True)
            (game/'game.exe').write_bytes(b'game')
            manifest={'id':'game','name':'Game','exe':'game.exe','args':['-first'],
                      '_game_dir':str(game),'enabled':True}
            server=FileSyncServer(private,game.parent,host='127.0.0.1',port=0,
                                  library_provider=lambda:{'game':manifest})
            await server.start()
            client_root=root/'client';client_root.mkdir()
            app=SimpleNamespace(library={},game_root=client_root,role='client',peer_file_server=None)
            app.after=lambda delay,callback:callback()
            app._client_library_updated=lambda:None
            app._publish_host_library=MethodType(LauncherCore._publish_host_library,app)
            try:
                with patch('lantool.launcher.APP_DIR',root/'state'):
                    await LauncherCore._fetch_host_library(app,'127.0.0.1',server.port,public)
                    self.assertEqual(app.library['game']['args'],['-first'])
                    manifest['args']=['+connect','{host_ip}','+name','{name}']
                    await LauncherCore._fetch_host_library(app,'127.0.0.1',server.port,public)
                    self.assertEqual(app.library['game']['args'],manifest['args'])
            finally:
                await server.stop()

    async def test_signed_playlist_visible_before_slow_game_scan(self):
        private, public = generate_keypair()
        body = json.dumps(sign_obj(private, {'type': 'library', 'games': [
            {'id': 'game', 'name': 'Game', 'exe': 'game.exe'}]})).encode()

        async def serve(reader, writer):
            await reader.readuntil(b'\r\n\r\n')
            writer.write(b'HTTP/1.0 200 OK\r\nContent-Length: ' + str(len(body)).encode() + b'\r\n\r\n' + body)
            await writer.drain()
            writer.close()

        server = await asyncio.start_server(serve, '127.0.0.1', 0)
        entered, release = asyncio.Event(), asyncio.Event()

        async def slow_scan(func, *args, **kwargs):
            if getattr(func, '__name__', '') == 'assign_client_folders':
                return func(*args, **kwargs)  # quick folder assignment; it runs before the playlist is published
            entered.set()
            await release.wait()
            return None

        with tempfile.TemporaryDirectory() as folder:
            published = []
            app = SimpleNamespace(library={}, game_root=Path(folder), role='client', peer_file_server=None)
            app._client_library_updated = lambda: published.append(dict(app.library))
            app.after = lambda delay, callback: callback()
            app._publish_host_library = MethodType(LauncherCore._publish_host_library, app)
            try:
                with patch('lantool.launcher.asyncio.to_thread', side_effect=slow_scan), \
                     patch('lantool.launcher.APP_DIR', Path(folder)):
                    task = asyncio.create_task(LauncherCore._fetch_host_library(
                        app, '127.0.0.1', server.sockets[0].getsockname()[1], public))
                    try:
                        await asyncio.wait_for(entered.wait(), 2)
                        self.assertFalse(task.done())
                        self.assertEqual(published[0]['game']['name'], 'Game')
                        release.set()
                        await task
                        # The fast display path must never publish an
                        # unverified playlist, even when the endpoint replies.
                        app.library = {}
                        published.clear()
                        _, wrong_public = generate_keypair()
                        with self.assertRaisesRegex(RuntimeError, 'signature is invalid'):
                            await LauncherCore._fetch_host_library(
                                app, '127.0.0.1', server.sockets[0].getsockname()[1], wrong_public)
                        self.assertEqual(published, [])
                    finally:
                        release.set()
                        if not task.done():
                            task.cancel()
                            await asyncio.gather(task, return_exceptions=True)
            finally:
                server.close()
                await server.wait_closed()

    async def test_lan_failure_falls_back_to_overlay(self):
        hosts = []
        app = SimpleNamespace(room_controller=object(), peer_file_server=None,
                              presence_client=None, syncing_game=True, last_beacon=None)

        async def fetch(host, port, public):
            hosts.append(host)
            if host == '192.168.1.10':
                raise OSError('LAN blocked')
            app.room_controller = None

        app._fetch_host_library = fetch
        with patch('lantool.launcher.asyncio.sleep', new=AsyncMock()):
            await LauncherCore._watch_host_library(app, {'host': '192.168.1.10',
                'host_zt': '10.147.20.1', 'host_pub': 'verified-host'})
        self.assertEqual(hosts, ['192.168.1.10', '10.147.20.1'])
