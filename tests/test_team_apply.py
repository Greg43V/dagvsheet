import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from app import DEFAULT_SHEET
from service_account_reader import LIVE_IMPORT_GID
from team_apply import apply_live, make_requests, verify_changes


def plan():
    return {'spreadsheet_id': DEFAULT_SHEET, 'sheet_id': LIVE_IMPORT_GID,
            'changes': [{'cell': 'I2', 'before': 'Arsenal ', 'after': 'afc'}],
            'mappings_sha256': 'test-hash', 'unknown': {'x': 2}}


class TeamApplyTests(unittest.TestCase):
    def test_requests_are_exact_and_limited_to_one_team_cell(self):
        request = make_requests(plan())[0]['findReplace']
        self.assertEqual(request['range'], {'sheetId': LIVE_IMPORT_GID, 'startRowIndex': 1, 'endRowIndex': 2, 'startColumnIndex': 8, 'endColumnIndex': 9})
        self.assertEqual(request['find'], 'Arsenal ')
        self.assertTrue(request['matchEntireCell'])
        self.assertTrue(request['matchCase'])
        self.assertFalse(request['includeFormulas'])
        self.assertFalse(request['searchByRegex'])

    def test_other_columns_headers_formulas_and_unapproved_replacements_rejected(self):
        for change in (
            {'cell': 'K2', 'before': 'Arsenal', 'after': 'afc'},
            {'cell': 'I1', 'before': 'Arsenal', 'after': 'afc'},
            {'cell': 'I2', 'before': '=LOOKUP(A2)', 'after': 'afc'},
            {'cell': 'I2', 'before': 'Arsenal', 'after': 'thfc'},
        ):
            value = plan()
            value['changes'] = [change]
            with self.assertRaises(ValueError):
                make_requests(value)

    @patch('team_apply.build_live_preview')
    def test_changed_sheet_aborts_before_write(self, preview):
        first, second = plan(), plan()
        second['changes'] = []
        preview.side_effect = [first, second]
        session = Mock()
        with self.assertRaises(ValueError):
            apply_live(session)
        session.post.assert_not_called()

    @patch('team_apply.read_team_rows')
    @patch('team_apply.build_live_preview')
    def test_success_records_original_values_and_verifies_live_result(self, preview, read):
        preview.side_effect = [plan(), plan()]
        read.return_value = ('Live import', [['Home team', 'Away team'], ['afc', 'x']])
        session = Mock()
        session.post.return_value.status_code = 200
        session.post.return_value.json.return_value = {'replies': [{'findReplace': {'valuesChanged': 1, 'formulasChanged': 0}}]}
        with tempfile.TemporaryDirectory() as folder:
            result = apply_live(session, audit_directory=Path(folder))
            self.assertEqual(result['status'], 'verified')
            self.assertIn('Arsenal ', Path(result['audit_file']).read_text())
            self.assertEqual(result['unknown_left_unchanged'], {'x': 2})

    def test_readback_detects_missing_or_shifted_values(self):
        self.assertEqual(verify_changes(plan()['changes'], [['Home team', 'Away team'], ['Arsenal', 'x']]), ['I2'])

    @patch('team_apply.build_live_preview')
    def test_uncertain_write_is_not_retried_and_audit_is_kept(self, preview):
        preview.side_effect = [plan(), plan()]
        session = Mock()
        session.post.side_effect = TimeoutError('test')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(TimeoutError):
                apply_live(session, audit_directory=Path(folder))
            self.assertEqual(session.post.call_count, 1)
            audit = next(Path(folder).glob('*.json')).read_text()
            self.assertIn('outcome_unconfirmed', audit)
            self.assertIn('Arsenal ', audit)


if __name__ == '__main__':
    unittest.main()
