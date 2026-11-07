"""Protected room admission and TLS service gating."""
import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from lantool.filesync.client import sync_game
from lantool.filesync.peer import PeerFileServer
from lantool.filesync.server import FileSyncServer
from lantool.filesync.index import build_index
from lantool.netcore.admission import AdmissionAccess, RoomAdmission, request_admission
from lantool.netcore.beacon import make_beacon, parse_beacon
from lantool.presence.server import PresenceServer
from lantool.trust.signing import generate_keypair
from silent_tunnel.quarantine import ADMISSION_PORT, protected_network_config


class RoomAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.room = RoomAdmission("test-password", port=0)
        self.addAsyncCleanup(self.room.stop)
        await self.room.start()
        self.beacon = {"host": "127.0.0.1", "admission": self.room.metadata}
        self.key = generate_keypair()

    async def request(self, **kwargs):
        return await request_admission(self.beacon, "player-1", "Player One", identity=self.key, **kwargs)

    async def require_approval(self):
        for _ in range(3):
            self.room._last_guess.clear()  # explicit submissions spaced past the host throttle
            self.assertEqual((await self.request(password="wrong"))["status"], "wrong_password")
        self.room._last_guess.clear()
        pending = await self.request(password="test-password")
        self.assertEqual(pending["status"], "pending")
        return pending["request_id"]

    async def test_host_rejects_signed_admission_from_a_different_release(self):
        from lantool.netcore import admission
        original = admission.signing.sign_obj
        with patch.object(admission.signing, 'sign_obj', side_effect=lambda private, body:
                          original(private, dict(body, launcher_version='0.9.24'))):
            result = await self.request(password='test-password')
        self.assertEqual(result['status'], 'version_mismatch')
        self.assertEqual(self.room._grants, {})

    async def test_three_guesses_then_approval(self):
        self.assertEqual((await self.request())["status"], "password_required")
        request_id = await self.require_approval()
        self.assertEqual(self.room.snapshot()["pending"],
                         [{"id": request_id, "name": "Player One", "ip": "127.0.0.1"}])
        self.assertEqual((await self.request(action="poll", request_id=request_id))["status"], "pending")
        self.assertTrue(self.room.decide(request_id, True))
        allowed = await self.request(action="poll", request_id=request_id)
        self.assertEqual(allowed["status"], "allowed")
        self.assertTrue(self.room.permits(allowed["token"], "player-1", ip="127.0.0.1"))
        self.assertFalse(self.room.permits(allowed["token"], "player-2"))
        self.assertEqual(self.room.snapshot()["pending"], [])

    async def test_authenticated_return_rebinds_physical_address(self):
        from lantool._version import __version__, __proto__
        body = {'action': 'join', 'identity': self.key[1], 'player_id': 'player-1',
                'name': 'Player', 'password': 'test-password',
                'launcher_version': __version__, 'proto': __proto__}
        first = self.room._process(body, '192.168.1.10')
        returned = self.room._process(body, '192.168.1.20')
        self.assertEqual(returned['status'], 'allowed')
        self.assertTrue(self.room.permits(returned['token'], 'player-1', ip='192.168.1.20'))
        self.assertFalse(self.room.permits(first['token'], 'player-1', ip='192.168.1.10'))
        body['password'] = 'wrong'
        self.room._process(body, '192.168.1.30')
        self.assertFalse(self.room.permits(returned['token'], 'player-1', ip='192.168.1.30'))

    async def test_deny_blocks_retries_and_room_close_clears(self):
        request_id = await self.require_approval()
        self.assertTrue(self.room.decide(request_id, False))
        self.assertEqual((await self.request(action="poll", request_id=request_id))["status"], "denied")
        self.assertEqual((await self.request(password="test-password"))["status"], "denied")
        self.assertEqual(self.room.snapshot()["blacklist"][0]["ip"], "127.0.0.1")
        self.assertTrue(self.room.remove(request_id))
        self.assertEqual((await self.request())["status"], "password_required")
        await self.room.stop()
        self.assertEqual(self.room.snapshot(), {"pending": [], "blacklist": []})

    async def test_cancel_leaves_approval_requirement_in_place(self):
        request_id = await self.require_approval()
        self.assertEqual((await self.request(action="cancel", request_id=request_id))["status"], "cancelled")
        self.assertFalse(self.room.decide(request_id, True))
        self.room._last_guess.clear()
        self.assertEqual((await self.request(password="test-password"))["status"], "pending")

    async def test_protected_services_require_tls_and_token(self):
        result = await self.request(password="test-password")
        access = AdmissionAccess.from_result(self.beacon, result)
        with tempfile.TemporaryDirectory() as folder:
            private, public = generate_keypair()
            game = Path(folder) / "shared" / "demo"
            game.mkdir(parents=True)
            (game / "demo.txt").write_text("Game file", encoding="utf-8")
            files = FileSyncServer(private, game.parent, host="127.0.0.1", port=0,
                                   admission=self.room)
            presence = PresenceServer(host="127.0.0.1", port=0, admission=self.room)
            peer = PeerFileServer(Path(folder), host="127.0.0.1", port=0)
            await files.start()
            await presence.start()
            await peer.start()
            try:
                with self.assertRaises(OSError):
                    await replace(access, fingerprint="0" * 64).connect("127.0.0.1", files.port)
                for header, code in ((b"", b"403"), (access.authorization_header, b"200")):
                    reader, writer = await access.connect("127.0.0.1", files.port)
                    try:
                        writer.write(b"GET /library HTTP/1.0\r\n" + header + b"\r\n")
                        await writer.drain()
                        self.assertEqual((await asyncio.wait_for(reader.readline(), 2)).split()[1], code)
                    finally:
                        writer.close()
                reader, writer = await access.connect("127.0.0.1", presence.port)
                try:
                    writer.write(b'{"type":"hello","player_id":"player-1"}\n')
                    await writer.drain()
                    self.assertEqual(await asyncio.wait_for(reader.read(), 2), b"")
                finally:
                    writer.close()
                dest = Path(folder) / "download"
                result = await sync_game("127.0.0.1", files.port, public, "demo", dest, access=access)
                self.assertTrue(result.ok, result.error)
                self.assertEqual((dest / "demo.txt").read_text(), "Game file")
                peer.register_index("demo", game, build_index("demo", game)["files"])
                peer.set_shared_files({"demo": ["demo.txt"]})
                swarmed = await sync_game("127.0.0.1", files.port, public, "demo",
                                          Path(folder) / "peer-download", access=access,
                                          peers=[{"host": "127.0.0.1", "port": peer.port,
                                                  "games": ["demo"]}])
                self.assertTrue(swarmed.ok, swarmed.error)
                self.assertGreater(sum(row["bytes"] for row in peer.activity.snapshot("demo")), 0)
            finally:
                await peer.stop()
                await presence.stop()
                await files.stop()

    async def test_overlay_binding_requires_valid_token_and_matching_identity(self):
        overlay = Mock(host_ip="127.0.0.1")
        overlay.node_for_ip.return_value = "aabbccddee"
        self.room._overlay = overlay
        result = await self.request(password="test-password")
        token = result["token"]
        invalid = await self.request(action="bind", token="guessed")
        self.assertEqual(invalid["status"], "denied")
        overlay.admit.assert_not_called()
        result = await self.request(action="bind", token=token)
        self.assertEqual(result["status"], "allowed")
        overlay.admit.assert_called_once_with("aabbccddee")

        request_id = await self.require_approval()
        self.assertTrue(self.room.decide(request_id, False))
        await asyncio.gather(*tuple(self.room._revocations))
        overlay.block.assert_called_once_with("aabbccddee")
        self.assertFalse(self.room.permits(token))


class AdmissionMetadataTests(unittest.TestCase):
    def test_admission_metadata_is_signed_and_validated(self):
        private, public = generate_keypair()
        meta = {"port": ADMISSION_PORT, "fingerprint": hashlib.sha256(b"test-cert").hexdigest(),
                "required": True}
        args = private, "a" * 16, "127.0.0.1", 47800, "", "0.9.00"
        self.assertEqual(parse_beacon(make_beacon(*args, host_pub=public, admission=meta))["admission"], meta)
        self.assertIsNone(parse_beacon(make_beacon(*args, host_pub=public,
                                                  admission={**meta, "port": True})))

    def test_overlay_rules_end_in_drop_and_limit_bootstrap_ports(self):
        config = protected_network_config("aabbccddee")
        rules = config["rules"]
        self.assertEqual(rules[-1], {"type": "ACTION_DROP"})
        self.assertEqual({rule["start"] for rule in rules if rule["type"].endswith("_PORT_RANGE")},
                         {47802, ADMISSION_PORT})
        self.assertEqual({rule["type"] for rule in rules[-5:-3]}, {"MATCH_TAG_SENDER", "MATCH_TAG_RECEIVER"})
