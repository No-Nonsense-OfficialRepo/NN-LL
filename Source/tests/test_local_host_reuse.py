"""Same-PC Clients reuse the verified Host source instead of syncing to themselves."""
import json
import tempfile
import unittest
from pathlib import Path
from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from lantool import launcher as core
from lantool.filesync.server import FileSyncServer
from lantool.game_directory import save_catalog
from lantool.install_manifest import shared_matches
from lantool.trust.signing import generate_keypair


class LocalHostReuseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.host_root = self.root / 'host-games'
        self.source = self.host_root / 'Half-Life'
        self.source.mkdir(parents=True)
        (self.source / 'data.bin').write_bytes(b'Already present in the Host source')
        self.state = self.root / 'state'
        self.state.mkdir()
        self.private, self.public = generate_keypair()
        (self.state / 'host_identity.json').write_text(json.dumps({'public': self.public}), encoding='utf-8')
        self.entry = {'id': 'half-life', 'name': 'Half-Life', 'exe': '', 'exe_required': False,
                      '_game_dir': str(self.source), 'enabled': True}
        save_catalog(self.state / 'host_games.json', {'half-life': self.entry})
        self.catalog = {'half-life': self.entry}
        self.server = FileSyncServer(self.private, self.host_root, host='127.0.0.1', port=0,
                                     library_provider=lambda: self.catalog)
        await self.server.start()
        self.patches = [patch.object(core, 'APP_DIR', self.state),
                        patch.object(core, 'GAME_FILES_ROOT', self.host_root)]
        for item in self.patches:
            item.start()
        self.client = SimpleNamespace(library={}, role='client', game_root=self.root / 'client-downloads',
                                      peer_file_server=None, after=lambda delay, fn: fn(),
                                      _client_library_updated=lambda: None)
        self.client._publish_host_library = MethodType(core.LauncherCore._publish_host_library, self.client)

    async def asyncTearDown(self):
        await self.server.stop()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    async def fetch(self):
        await core.LauncherCore._fetch_host_library(self.client, '127.0.0.1', self.server.port, self.public)
        return self.client.library['half-life']

    async def test_file_only_host_source_needs_no_client_receipt_or_self_download(self):
        manifest = await self.fetch()
        self.assertEqual(Path(manifest['install_dir']).resolve(), self.source.resolve())
        self.assertFalse(shared_matches(self.source, 'half-life'))
        self.assertTrue(core.LauncherCore._local_host_source_matches(manifest))
        self.assertTrue(core.LauncherCore._prepare_client_game(self.client, manifest))
        status = Mock()
        self.client.pages = {'room': SimpleNamespace(set_status=status)}
        # This guard returns before even requiring room/network state and never
        # requests an index or creates a duplicate client-downloads directory.
        core.LauncherCore._sync_then_play(self.client, manifest, {}, launch_after=False)
        self.assertIn('already available', status.call_args.args[0])
        self.assertEqual(self.server.requests, [])
        self.assertFalse(self.client.game_root.exists())
        self.assertFalse(shared_matches(self.source, 'half-life'))
        self.client.syncing_game = False
        self.client.peer_file_server = object()
        with patch('lantool.filesync.client.fetch_index', new=AsyncMock()) as index:
            await core.LauncherCore._seed_existing_games(self.client, {})
            index.assert_not_awaited()

    async def test_remote_signed_marker_does_not_attest_local_files(self):
        _, other_public = generate_keypair()
        (self.state / 'host_identity.json').write_text(json.dumps({'public': other_public}), encoding='utf-8')
        self.entry['_local_host_source'] = str(self.source)
        manifest = await self.fetch()
        self.assertNotIn('_local_host_source', manifest)
        self.assertEqual(Path(manifest['install_dir']), self.client.game_root / 'half-life')
        self.assertFalse(core.LauncherCore._prepare_client_game(self.client, manifest))

    async def test_only_matching_enabled_local_catalog_entry_is_reused(self):
        local = {**self.entry, 'enabled': False}
        save_catalog(self.state / 'host_games.json', {'half-life': local})
        manifest = await self.fetch()
        self.assertNotIn('_local_host_source', manifest)

    async def test_periodic_refresh_keeps_local_source_installed_in_initial_publish(self):
        await self.fetch()
        published = []
        original_publish = self.client._publish_host_library
        def observe(library):
            published.append(dict(library))
            original_publish(library)
        self.client._publish_host_library = observe
        await self.fetch()
        self.assertTrue(published)
        self.assertTrue(all(core.LauncherCore._local_host_source_matches(row['half-life']) for row in published))

    async def test_executable_source_reused_only_if_signed_hash_matches(self):
        exe = self.source / 'game.exe'
        exe.write_bytes(b'Host executable')
        self.entry.update({'exe_required': True, 'exe': 'game.exe'})
        save_catalog(self.state / 'host_games.json', {'half-life': self.entry})
        manifest = await self.fetch()
        self.assertTrue(core.LauncherCore._local_host_source_matches(manifest))
        self.assertTrue(core.LauncherCore._prepare_client_game(self.client, manifest))
        mismatch = dict(manifest, exe_sha256='0' * 64)
        mismatch.pop('_local_host_source')
        mismatch['install_dir'] = str(self.client.game_root / 'half-life')
        catalog = core.LauncherCore._local_host_library(self.client, self.public)
        core.LauncherCore._reuse_local_host_source(mismatch, catalog)
        self.assertNotIn('_local_host_source', mismatch)


if __name__ == '__main__':
    unittest.main()
