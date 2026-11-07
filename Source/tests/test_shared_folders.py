import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace, MethodType

from lantool.game_directory import load_catalog, save_catalog
from lantool.manifests.loader import validate, resolve_exe, ManifestError
from lantool.install_manifest import shared_matches, mark_shared_installed
from lantool.filesync.server import FileSyncServer
from lantool.filesync.client import sync_game
from lantool.trust.signing import generate_keypair


class SharedFolderTests(unittest.TestCase):
    def test_explicit_opt_out_and_default_executable_requirement(self):
        entry = {'id': 'files', 'name': 'Shared files', 'exe': ''}
        with self.assertRaises(ManifestError):
            validate(entry)
        entry['exe_required'] = False
        self.assertEqual(validate(entry)['exe'], '')
        with self.assertRaises(ManifestError):
            resolve_exe(entry)
        with self.assertRaises(ManifestError):
            validate({**entry, 'exe_required': 'false'})

    def test_catalog_retains_no_exe_folder_and_install_receipt(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            game = root / 'games' / 'Files'
            game.mkdir(parents=True)
            entry = {'id': 'files', 'name': 'Shared files', 'exe': '', 'exe_required': False,
                     '_game_dir': str(game), 'enabled': True}
            save_catalog(root / 'catalog.json', {'files': entry})
            loaded = load_catalog(root / 'catalog.json', root / 'games', root / 'art')
            self.assertFalse(loaded['files']['exe_required'])
            self.assertTrue(loaded['files']['enabled'])
            self.assertFalse(shared_matches(game, 'files'))
            mark_shared_installed(game, 'files')
            self.assertTrue(shared_matches(game, 'files'))
            self.assertFalse(shared_matches(game, 'other-files'))


class SharedFolderTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_executable_required_for_verified_file_transfer(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / 'host' / 'files'
            source.mkdir(parents=True)
            (source / 'readme.txt').write_bytes(b'Files without a game executable')
            private, public = generate_keypair()
            catalog = {'files': {'id': 'files', 'name': 'Shared files', 'exe': '',
                                 'exe_required': False, '_game_dir': str(source), 'enabled': True}}
            server = FileSyncServer(private, root / 'host', host='127.0.0.1', port=0,
                                    library_provider=lambda: catalog)
            await server.start()
            try:
                from lantool.launcher import LauncherCore
                client = SimpleNamespace(library={}, game_root=root / 'downloads',
                                         peer_file_server=None, role='client',
                                         after=lambda *args: None, _client_library_updated=lambda: None)
                client._publish_host_library = MethodType(LauncherCore._publish_host_library, client)
                await LauncherCore._fetch_host_library(client, '127.0.0.1', server.port, public)
                self.assertFalse(client.library['files']['exe_required'])
                result = await sync_game('127.0.0.1', server.port, public, 'files', root / 'client')
                self.assertTrue(result.ok, result.error)
                self.assertEqual((root / 'client' / 'readme.txt').read_bytes(), b'Files without a game executable')
            finally:
                await server.stop()
