import json
import os
import unittest
from unittest.mock import Mock, patch

try:
    import service_account_reader as reader
except ImportError:
    reader = None


@unittest.skipIf(reader is None, 'Optional cloud service-account dependencies not installed; use .venv/bin/python')
class ServiceAccountTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_missing_key_is_a_clear_blocker(self):
        with self.assertRaisesRegex(ValueError, 'missing'):
            reader.credentials_from_environment()

    def test_wrong_account_or_token_destination_rejected_before_signing(self):
        for info in (
            {'type': 'service_account', 'client_email': 'wrong@example.com'},
            {'type': 'service_account', 'client_email': reader.EXPECTED_ACCOUNT, 'token_uri': 'https://other.example/token'},
        ):
            with patch.dict(os.environ, {'GOOGLE_SERVICE_ACCOUNT_JSON': json.dumps(info)}):
                with self.assertRaises(ValueError):
                    reader.credentials_from_environment()

    def test_read_is_bounded_to_live_import_and_has_no_write(self):
        session = Mock()
        session.get.return_value.status_code = 200
        session.get.return_value.json.return_value = {
            'properties': {'title': 'Test sales'}, 'sheets': [{
                'properties': {'title': 'Live import', 'sheetId': 2038894540},
                'data': [{'rowData': [{'values': [{'formattedValue': 'Home'}, {'formattedValue': 'Away'}]},
                                      {'values': [{'formattedValue': 'Arsenal'}, {'formattedValue': 'Tottenham'}]}]}],
            }],
        }
        data = reader.read_live_import(session)
        self.assertEqual(data['rows'][1], ['Arsenal', 'Tottenham'])
        self.assertEqual(session.get.call_args.kwargs['params']['ranges'], "'Live import'!A1:AZ200")
        self.assertEqual(data['tab'], 'Live import')
        session.post.assert_not_called()
        session.put.assert_not_called()

    def test_no_permission_response_is_not_reported_as_connected(self):
        session = Mock()
        session.get.return_value.status_code = 403
        with self.assertRaisesRegex(ValueError, '403'):
            reader.read_live_import(session)


if __name__ == '__main__':
    unittest.main()
