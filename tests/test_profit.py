from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import Mock, patch

from app import App, ConnectionError
from profit import PROFIT_GID, ProfitSnapshots, SnapshotStore, read_profit, scheduled_for, next_capture
from website import create_website


def moment(value):
    return datetime.fromisoformat(value)


def source(value=1234.56, label='Profit', gid=PROFIT_GID):
    return Mock(side_effect=[{'sheets': [{'properties': {'sheetId': gid, 'title': 'Live Profit'}}]},
                            {'values': [[label, value]]}])


class ProfitSourceTests(unittest.TestCase):
    def test_exact_identity_bounded_range_and_unrounded_value(self):
        get = source(267185.2113333333)
        self.assertEqual(read_profit(get)['value'], '267185.2113333333')
        self.assertIn('A1%3AB1', get.call_args_list[1].args[0])
        self.assertIn('UNFORMATTED_VALUE', get.call_args_list[1].args[0])

    def test_wrong_tab_does_not_fall_back(self):
        get = source(gid=123)
        with self.assertRaises(ConnectionError):
            read_profit(get)
        self.assertEqual(get.call_count, 1)

    def test_invalid_or_moved_figure_is_not_saved(self):
        for value, label in [('£1,000', 'Profit'), ('#REF!', 'Profit'), (True, 'Profit'),
                             ('NaN', 'Profit'), ('Infinity', 'Profit'), ('', 'Profit'),
                             (123, 'Revenue')]:
            with self.subTest(value=value, label=label), self.assertRaises(ConnectionError):
                read_profit(source(value, label))
        self.assertEqual(read_profit(source(0))['value'], '0')
        self.assertEqual(read_profit(source(-42))['value'], '-42')


class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'snapshots.sqlite3'
        self.store = SnapshotStore(self.path)

    def save(self, date, value):
        now = moment(date + 'T08:00:00+02:00')
        return self.store.save(now, scheduled_for(now)[1], value)

    def test_schedule_uses_south_african_calendar_and_overlap(self):
        self.assertEqual(scheduled_for(moment('2026-11-01T21:59:59+00:00')), ('2026-11-01', ['monthly']))
        self.assertEqual(scheduled_for(moment('2026-11-01T22:00:00+00:00')), ('2026-11-02', ['weekly']))
        self.assertEqual(scheduled_for(moment('2027-02-01T00:00:00+02:00')), ('2027-02-01', ['weekly', 'monthly']))
        self.assertEqual(scheduled_for(moment('2026-11-11T12:00:00+02:00'))[1], [])
        self.assertEqual(next_capture(moment('2026-12-31T12:00:00+02:00')), '2027-01-01')

    def test_duplicate_and_restart_preserve_first_capture(self):
        self.assertTrue(self.save('2026-11-02', '100.1234'))
        self.assertFalse(self.save('2026-11-02', '999'))
        history = SnapshotStore(self.path).history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]['value'], '100.1234')
        self.assertIsNone(history[0]['change'])

    def test_weekly_and_monthly_comparisons_use_their_own_previous_capture(self):
        for day, value in [('2027-01-01', '100'), ('2027-01-25', '200'), ('2027-02-01', '250')]:
            self.save(day, value)
        last = self.store.history()[0]
        self.assertEqual(last['kinds'], ['weekly', 'monthly'])
        self.assertEqual(last['comparisons']['weekly'], {
            'previousDate': '2027-01-25', 'previousValue': '200', 'change': '50', 'changePercent': '25.00'})
        self.assertEqual(last['comparisons']['monthly']['change'], '150')
        self.assertEqual(last['comparisons']['monthly']['previousDate'], '2027-01-01')

    def test_zero_and_negative_baselines_have_safe_comparisons(self):
        for day, value in [('2026-11-02', '-100'), ('2026-11-09', '0'), ('2026-11-16', '50')]:
            self.save(day, value)
        history = self.store.history()
        self.assertIsNone(history[0]['comparisons']['weekly']['changePercent'])
        self.assertEqual(history[1]['comparisons']['weekly']['changePercent'], '100')

    def test_sheet_histories_are_isolated(self):
        self.save('2026-11-02', '100')
        self.assertEqual(SnapshotStore(self.path, 'another-sheet').history(), [])

    def test_worker_retries_failure_without_backfilling_or_overwriting(self):
        read = Mock(side_effect=[ConnectionError('failed'), {'value': '100'}])
        worker = ProfitSnapshots('sheet', self.store, read)
        monday = moment('2026-11-02T08:00:00+02:00')
        with self.assertRaises(ConnectionError):
            worker.tick(monday)
        self.assertEqual(self.store.history(), [])
        self.assertTrue(worker.tick(monday))
        self.assertFalse(worker.tick(monday))
        self.assertFalse(worker.tick(moment('2026-11-03T08:00:00+02:00')))
        self.assertEqual(read.call_count, 2)

    def test_read_crossing_midnight_is_not_assigned_to_wrong_date(self):
        worker = ProfitSnapshots('sheet', self.store, Mock(return_value={'value': '100'}))
        with patch('profit.datetime') as clock:
            clock.now.side_effect = [moment('2026-11-02T21:59:59+00:00'), moment('2026-11-02T22:00:01+00:00')]
            self.assertFalse(worker.tick())
        self.assertEqual(self.store.history(), [])

    def test_setup_required_without_unattended_reader_or_persistent_store(self):
        for store, read in [(self.store, None), (None, Mock())]:
            worker = ProfitSnapshots('sheet', store, read)
            worker.start()
            self.assertIsNone(worker.thread)
            self.assertFalse(worker.tick())
            self.assertEqual(worker.summary()['state'], 'setup_required')


class ProfitApiTests(unittest.TestCase):
    def setUp(self):
        self.connection = App('https://dashboard.example', {'client_id': 'id', 'client_secret': 'secret'})
        self.snapshots = Mock()
        self.snapshots.summary.return_value = {'state': 'setup_required', 'history': []}
        self.client = create_website(self.connection, self.snapshots).test_client()

    def sign_in(self, expired=False):
        sid, browser = self.connection.session(None)
        browser.update(token='private-token', token_expires=time.time() + (-5 if expired else 300))
        self.client.set_cookie('dagvsheet', sid)

    @patch('website.google_json')
    def test_anonymous_and_expired_users_cannot_read_figure_or_history(self, google):
        self.assertEqual(self.client.get('/api/profit').status_code, 401)
        self.sign_in(expired=True)
        self.assertEqual(self.client.get('/api/profit').status_code, 401)
        google.assert_not_called()
        self.snapshots.summary.assert_not_called()

    @patch('website.google_json')
    def test_history_requires_fresh_browser_sheet_permission(self, google):
        self.sign_in()
        google.side_effect = ConnectionError('Google access was denied.')
        self.assertEqual(self.client.get('/api/profit').status_code, 400)
        self.snapshots.summary.assert_not_called()

    @patch('website.google_json')
    def test_authenticated_read_does_not_return_token_or_offer_write_route(self, google):
        self.sign_in()
        google.side_effect = source().side_effect
        response = self.client.get('/api/profit')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['figure']['value'], '1234.56')
        self.assertNotIn('private-token', response.get_data(as_text=True))
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        for call in google.call_args_list:
            self.assertEqual(call.kwargs['token'], 'private-token')
        self.assertEqual(self.client.post('/api/profit').status_code, 405)


if __name__ == '__main__':
    unittest.main()
