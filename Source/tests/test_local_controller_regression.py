import unittest
from unittest.mock import patch

from silent_tunnel.local import LocalClient
from silent_tunnel.authorizer import AutoAuthorizer


class LocalControllerRegression(unittest.TestCase):
    def test_join_allows_adapter_creation_without_slowing_status(self):
        client = LocalClient(token='test', port=9993)
        with patch('silent_tunnel.local.request_json', return_value={}) as request:
            client.join('abcdef0123456789')
            self.assertEqual(request.call_args.args[-1], 60)
            client.status()
            self.assertEqual(request.call_args.args[-1], 5)

    def test_flat_authorized_member_is_not_reauthorized(self):
        client = LocalClient(token='test')
        with patch.object(client, '_call', side_effect=[
                {'aabbccddee': 1}, {'id': 'aabbccddee', 'authorized': True}]), \
                patch.object(client, 'authorize_member') as authorize:
            authorizer = AutoAuthorizer(client, 'abcdef0123456789', 'aabbccddee', '10.147.20.1')
            self.assertEqual(authorizer.poll_once(), [])
            authorize.assert_not_called()

    def test_flat_unapproved_member_is_authorized(self):
        client = LocalClient(token='test')
        with patch.object(client, '_call', return_value=[{'id': 'aabbccddee', 'authorized': False}]), \
                patch.object(client, 'authorize_member') as authorize:
            authorizer = AutoAuthorizer(client, 'abcdef0123456789', 'aabbccddee', '10.147.20.1')
            self.assertEqual(authorizer.poll_once(), ['aabbccddee'])
            authorize.assert_called_once()
