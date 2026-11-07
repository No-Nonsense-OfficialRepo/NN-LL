import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from silent_tunnel import Tunnel
from silent_tunnel.errors import ServiceError


class CleanupRecoveryTests(unittest.TestCase):
    def test_failed_leave_survives_restart_and_is_retried(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Mock()
            local.leave.side_effect = ServiceError('Service unavailable')
            tunnel = Tunnel(home=Path(folder), local=local)
            tunnel._remember('8056c2e21c000001')
            self.assertEqual(tunnel.cleanup(uninstall=False), ['Service unavailable'])
            restarted = Tunnel(home=Path(folder), local=Mock())
            self.assertEqual(restarted.state.joined, ['8056c2e21c000001'])
            self.assertEqual(restarted.recover(), [])
            restarted.local.leave.assert_called_once_with('8056c2e21c000001')
            self.assertEqual(restarted.state.joined, [])
            self.assertEqual(Tunnel(home=Path(folder)).state.joined, [])

    def test_host_leave_failure_retains_membership_after_controller_deletion(self):
        with tempfile.TemporaryDirectory() as folder:
            local = Mock()
            local.leave.side_effect = ServiceError('Service unavailable')
            tunnel = Tunnel(home=Path(folder), local=local)
            tunnel._remember('8056c2e21c000001')
            tunnel.state.hosted_network = '8056c2e21c000001'
            self.assertEqual(tunnel.close_room(), ['Service unavailable'])
            persisted = Tunnel(home=Path(folder))
            self.assertEqual(persisted.state.joined, ['8056c2e21c000001'])
            self.assertEqual(persisted.state.hosted_network, '')
