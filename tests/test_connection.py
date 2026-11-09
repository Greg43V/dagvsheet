import hashlib
import base64
import http.cookiejar
import json
import threading
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from unittest.mock import patch

from app import App, ConnectionError, SCOPE, ThreadingHTTPServer, make_handler


class ConnectionTests(unittest.TestCase):
    def setUp(self):
        self.app = App('https://agent.example', {'client_id': 'test-id', 'client_secret': 'test-secret'})

    def pending(self, session):
        return urllib.parse.parse_qs(urllib.parse.urlsplit(self.app.authorize(session)).query)

    def test_authorization_uses_readonly_pkce_and_registered_callback(self):
        session = {}
        query = self.pending(session)
        self.assertEqual(query['scope'], [SCOPE])
        self.assertEqual(query['redirect_uri'], ['https://agent.example/oauth/callback'])
        expected = base64.urlsafe_b64encode(hashlib.sha256(session['oauth']['verifier'].encode()).digest()).decode().rstrip('=')
        self.assertEqual(query['code_challenge'], [expected])

    @patch('app.google_json')
    def test_callback_is_bound_to_browser_state_and_single_use(self, google):
        session = {}
        query = self.pending(session)
        google.return_value = {'access_token': 'test-token', 'scope': SCOPE, 'expires_in': 3600}
        self.app.finish(session, {'state': query['state'], 'code': ['test-code']})
        self.assertEqual(session['token'], 'test-token')
        self.assertIn('code_verifier', google.call_args.kwargs['form'])
        with self.assertRaises(ConnectionError):
            self.app.finish(session, {'state': query['state'], 'code': ['test-code']})
        self.assertEqual(google.call_count, 1)

    @patch('app.google_json')
    def test_wrong_state_expired_request_and_denial_never_exchange_code(self, google):
        for mode in ('wrong', 'expired', 'denied'):
            session = {}
            query = self.pending(session)
            params = {'state': query['state'], 'code': ['test-code']}
            if mode == 'wrong':
                params['state'] = ['bad']
            if mode == 'expired':
                session['oauth']['created'] -= 601
            if mode == 'denied':
                params['error'] = ['access_denied']
            with self.assertRaises(ConnectionError):
                self.app.finish(session, params)
        google.assert_not_called()

    @patch('app.google_json')
    def test_missing_scope_does_not_connect(self, google):
        session = {}
        query = self.pending(session)
        google.return_value = {'access_token': 'test-token', 'scope': 'unrelated'}
        with self.assertRaises(ConnectionError):
            self.app.finish(session, {'state': query['state'], 'code': ['test-code']})
        self.assertNotIn('token', session)

    @patch('app.google_json')
    def test_reads_exact_tab_with_quoted_name_and_bounded_range(self, google):
        google.side_effect = [
            {'properties': {'title': 'Test sheet'}, 'sheets': [
                {'properties': {'sheetId': 0, 'title': 'Wrong tab'}},
                {'properties': {'sheetId': 2038894540, 'title': "Client's rows"}},
            ]},
            {'values': [['Name', 'Value'], ['Example', '42']]},
        ]
        result = self.app.read_sheet({'token': 'test-token', 'token_expires': time.time() + 300})
        self.assertEqual(result['tab'], "Client's rows")
        self.assertEqual(result['rows'][1], ['Example', '42'])
        url = urllib.parse.unquote(google.call_args.args[0])
        self.assertIn("'Client''s rows'!A1:AZ200", url)
        self.assertTrue(result['readOnly'])

    @patch('app.google_json')
    def test_missing_tab_does_not_fall_back_to_another_tab(self, google):
        google.return_value = {'properties': {'title': 'Test'}, 'sheets': []}
        with self.assertRaises(ConnectionError):
            self.app.read_sheet({'token': 'test-token', 'token_expires': time.time() + 300})
        self.assertEqual(google.call_count, 1)

    @patch('app.google_json')
    def test_unauthorized_and_expired_sessions_do_not_read_google(self, google):
        for session in ({}, {'token': 'old', 'token_expires': time.time() - 5}):
            with self.assertRaises(ConnectionError):
                self.app.read_sheet(session)
        google.assert_not_called()

    def test_unknown_cookies_do_not_select_another_session(self):
        sid, session = self.app.session(None)
        session['token'] = 'private-test-token'
        other, second = self.app.session('dagvsheet=guessed')
        self.assertNotEqual(sid, other)
        self.assertNotIn('token', second)
        self.assertIs(self.app.session('dagvsheet=' + sid)[1], session)

    def test_public_callback_requires_https(self):
        with self.assertRaises(ValueError):
            App('http://public.example')


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.app = App('https://agent.example', {'client_id': 'id', 'client_secret': 'secret'})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), make_handler(self.app))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = 'http://127.0.0.1:' + str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_home_health_and_unauthorized_sheet(self):
        with urllib.request.urlopen(self.base + '/') as response:
            self.assertIn(b'Connect your private sheet', response.read())
            self.assertIn('HttpOnly', response.headers['Set-Cookie'])
            self.assertIn('Secure', response.headers['Set-Cookie'])
        with urllib.request.urlopen(self.base + '/healthz') as response:
            self.assertEqual(json.load(response)['status'], 'ok')
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(self.base + '/api/sheet')
        self.assertEqual(caught.exception.code, 400)

    def test_wrong_origin_disconnect_rejected(self):
        request = urllib.request.Request(self.base + '/disconnect', data=b'', headers={'Origin': 'https://other.example'})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
