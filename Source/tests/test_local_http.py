import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

from silent_tunnel._http import HttpError, request_json


class LocalHttpTests(unittest.TestCase):
    def test_local_requests_ignore_tls_setup_and_refuse_redirects(self):
        calls = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                calls.append((self.path, self.headers.get('X-ZT1-Auth')))
                self.send_response(302 if self.path == '/redirect' else 200)
                if self.path == '/redirect':
                    self.send_header('Location', '/leaked')
                self.end_headers()
                self.wfile.write(b'{"online":true}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            url = f'http://127.0.0.1:{server.server_port}'
            with patch('ssl._create_default_https_context', side_effect=FileNotFoundError('missing TLS file')):
                self.assertEqual(request_json('GET', url + '/status', {'X-ZT1-Auth': 'test-key'}), {'online': True})
                with self.assertRaises(HttpError) as error:
                    request_json('GET', url + '/redirect', {'X-ZT1-Auth': 'test-key'})
                self.assertEqual(error.exception.status, 302)
            self.assertEqual(calls, [('/status', 'test-key'), ('/redirect', 'test-key')])
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
