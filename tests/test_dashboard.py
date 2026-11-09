import time
import os
import unittest
from unittest.mock import patch

from app import App, ConnectionError
from orders import parse_orders, read_orders
from website import create_website

HEADERS = ['paid', 'paid by', 'order date', 'paid to', 'Event Date', 'Account', 'Order no', 'Home team', 'Away Team', 'quan', 'cat', 'Unit price', 'Total £ Price', 'Purchase Price', 'Profit', 'Seat info', 'Allocation', 'Notes', 'Order ID']


def order(number='ONE', *, price=0, quantity=2, total=500):
    row = [''] * len(HEADERS)
    for index, value in {6: number, 7: 'Arsenal', 8: 'Chelsea', 9: quantity, 10: 'Shortside upper', 11: 250, 12: total, 13: price, 16: 'Supplier name', 18: 'ID-' + number}.items():
        row[index] = value
    return row


class OrderTests(unittest.TestCase):
    def test_individual_orders_are_not_grouped_and_zero_price_overrides_supplier(self):
        data = parse_orders([HEADERS, order('ONE'), order('TWO', price=100)])
        self.assertEqual(len(data), 2)
        self.assertEqual([row['status'] for row in data], ['unallocated', 'allocated'])
        self.assertEqual(data[0]['home'], 'afc')
        self.assertEqual(data[0]['away'], 'cfc')
        self.assertEqual(data[0]['sourceRow'], 2)
        self.assertIn('range=A2:S2', data[0]['sourceUrl'])
        self.assertEqual(data[0]['totalSales'], 500)

    def test_invalid_prices_and_missing_quantities_are_visible(self):
        for price in ('', -1, 'unconfirmed', 'NaN'):
            data = parse_orders([HEADERS, order(price=price, quantity='')])[0]
            self.assertEqual(data['status'], 'review')
            self.assertIsNone(data['quantity'])
            self.assertIn('Check quantity', data['issues'])

    def test_sums_and_unit_prices_are_not_invented_from_missing_data(self):
        data = parse_orders([HEADERS, order(total='')])[0]
        self.assertIsNone(data['totalSales'])
        self.assertIn('Check total sales price', data['issues'])

    def test_blank_rows_and_missing_headers(self):
        self.assertEqual(parse_orders([HEADERS, []]), [])
        with self.assertRaises(ConnectionError):
            parse_orders([['Wrong header'], order()])

    def test_reads_correct_tab_identity_and_all_rows(self):
        responses = iter([
            {'properties': {'title': 'Test'}, 'sheets': [{'properties': {'sheetId': 1800395594, 'title': 'Grove Orders'}}]},
            {'values': [HEADERS, order()]},
        ])
        urls = []
        def get(url):
            urls.append(url)
            return next(responses)
        data = read_orders(get)
        self.assertTrue(data['readOnly'])
        self.assertEqual(len(data['orders']), 1)
        self.assertIn('A1%3AS', urls[1])
        self.assertNotIn('A1%3AS200', urls[1])


class WebsiteTests(unittest.TestCase):
    def setUp(self):
        self.connection = App('https://dashboard.example', {'client_id': 'test-id', 'client_secret': 'test-secret'})
        self.site = create_website(self.connection)
        self.client = self.site.test_client()

    def sign_in(self):
        sid, browser = self.connection.session(None)
        browser['token'] = 'private-test-token'
        browser['token_expires'] = time.time() + 300
        self.client.set_cookie('dagvsheet', sid)

    def test_dashboard_and_health_without_exposing_private_data(self):
        self.assertEqual(self.client.get('/healthz').json, {'status': 'ok'})
        page = self.client.get('/')
        self.assertIn(b'The buying desk', page.data)
        self.assertIn('HttpOnly', page.headers['Set-Cookie'])
        self.assertIn('Secure', page.headers['Set-Cookie'])
        self.assertEqual(page.headers['Cache-Control'], 'no-store')
        page.close()
        self.assertEqual(self.client.get('/api/orders').status_code, 401)

    @patch('website.google_json')
    def test_authenticated_orders_use_only_the_browser_token(self, google):
        self.sign_in()
        google.side_effect = [
            {'properties': {'title': 'Test'}, 'sheets': [{'properties': {'sheetId': 1800395594, 'title': 'Grove Orders'}}]},
            {'values': [HEADERS, order()]},
        ]
        response = self.client.get('/api/orders')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['orders'][0]['status'], 'unallocated')
        self.assertNotIn('private-test-token', response.get_data(as_text=True))
        for call in google.call_args_list:
            self.assertEqual(call.kwargs['token'], 'private-test-token')

    def test_expired_session_loses_data_access(self):
        sid, browser = self.connection.session(None)
        browser.update(token='old', token_expires=time.time() - 1)
        self.client.set_cookie('dagvsheet', sid)
        self.assertEqual(self.client.get('/api/orders').status_code, 401)

    def test_logout_origin_check_and_unimplemented_write_routes(self):
        self.sign_in()
        self.assertEqual(self.client.post('/disconnect', headers={'Origin': 'https://untrusted.example'}).status_code, 403)
        self.assertEqual(self.client.post('/api/orders').status_code, 405)
        self.assertEqual(self.client.post('/disconnect', headers={'Origin': 'https://dashboard.example'}).status_code, 200)
        self.assertEqual(self.client.get('/api/orders').status_code, 401)

    def test_oauth_redirect_keeps_existing_state_and_pkce_flow(self):
        response = self.client.get('/connect')
        self.assertEqual(response.status_code, 303)
        self.assertTrue(response.headers['Location'].startswith('https://accounts.google.com/'))
        self.assertIn('code_challenge=', response.headers['Location'])
        self.assertIn('state=', response.headers['Location'])

    def test_missing_credentials_return_to_dashboard_and_name_only_missing_fields(self):
        for values, expected in [
            ({}, ['GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET']),
            ({'GOOGLE_CLIENT_ID': 'test-client-id'}, ['GOOGLE_CLIENT_SECRET']),
            ({'GOOGLE_CLIENT_SECRET': 'test-secret-value'}, ['GOOGLE_CLIENT_ID']),
        ]:
            with self.subTest(expected=expected), patch.dict(os.environ, values, clear=True), patch('app.Path.is_file', return_value=False):
                client = create_website(App('https://dashboard.example')).test_client()
                response = client.get('/connect')
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers['Location'], '/')
                message = client.get('/api/status').json['error']
                for name in expected:
                    self.assertIn(name, message)
                for name in {'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET'} - set(expected):
                    self.assertNotIn(name, message)
                self.assertNotIn('test-secret-value', message)
                self.assertEqual(client.get('/api/orders').status_code, 401)

    @patch.dict(os.environ, {}, clear=True)
    def test_first_deployment_starts_before_public_domain_configuration(self):
        client = create_website().test_client()
        self.assertEqual(client.get('/healthz').status_code, 200)
        self.assertEqual(client.get('/api/orders').status_code, 401)
        self.assertEqual(client.get('/connect').headers['Location'], '/')
        self.assertIn('Generate a Railway domain', client.get('/api/status').json['error'])

    @patch.dict(os.environ, {'RAILWAY_PUBLIC_DOMAIN': 'buying-desk.up.railway.app',
                             'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret'}, clear=True)
    def test_railway_domain_automatically_configures_https_callback(self):
        client = create_website().test_client()
        response = client.get('/connect')
        self.assertIn('https%3A%2F%2Fbuying-desk.up.railway.app%2Foauth%2Fcallback', response.headers['Location'])
        self.assertIn('Secure', response.headers['Set-Cookie'])

    @patch.dict(os.environ, {'APP_BASE_URL': 'https://orders.example.com',
                             'RAILWAY_PUBLIC_DOMAIN': 'buying-desk.up.railway.app',
                             'GOOGLE_CLIENT_ID': 'test-id', 'GOOGLE_CLIENT_SECRET': 'test-secret'}, clear=True)
    def test_explicit_custom_domain_takes_precedence(self):
        response = create_website().test_client().get('/connect')
        self.assertIn('https%3A%2F%2Forders.example.com%2Foauth%2Fcallback', response.headers['Location'])


if __name__ == '__main__':
    unittest.main()
