import unittest

from team_mapping import load_mappings, preview


class TeamMappingTests(unittest.TestCase):
    def setUp(self):
        self.mappings = load_mappings()

    def test_variants_and_both_columns_follow_saved_preferences(self):
        plan = preview([['Home team', 'Away team'], ['Arsenal ', ' spurs '], [' hull', 'Ipswich Town'], ['s Hull', 'Tottenham Hotspur']], self.mappings)
        self.assertEqual([(c['cell'], c['after']) for c in plan['changes']],
                         [('I2', 'afc'), ('J2', 'thfc'), ('I3', 'hull'), ('J3', 'ipswich'), ('I4', 'hull'), ('J4', 'thfc')])

    def test_unknown_and_blank_values_are_not_guessed(self):
        plan = preview([['Home team', 'Away team'], ['x', ''], ['New unseen club', 'x']], self.mappings)
        self.assertEqual(plan['changes'], [])
        self.assertEqual(plan['unknown'], {'x': 1, 'New unseen club': 1})

    def test_first_data_row_x_is_silent_but_other_rows_are_still_flagged(self):
        plan = preview([['Home team', 'Away team'], [' x ', 'X'], ['x', 'Arsenal']], self.mappings)
        self.assertEqual(plan['unknown'], {'x': 1})
        self.assertEqual(plan['changes'], [{'cell': 'J3', 'before': 'Arsenal', 'after': 'afc'}])

    def test_first_data_row_real_teams_are_still_mapped(self):
        plan = preview([['Home team', 'Away team'], ['x', 'Arsenal']], self.mappings)
        self.assertEqual(plan['unknown'], {})
        self.assertEqual(plan['changes'], [{'cell': 'J2', 'before': 'Arsenal', 'after': 'afc'}])

    def test_existing_codes_are_stable_but_case_is_corrected(self):
        plan = preview([['Home team', 'Away team'], ['afc', 'THFC'], ['ipswich', 'hull']], self.mappings)
        self.assertEqual(plan['changes'], [{'cell': 'J2', 'before': 'THFC', 'after': 'thfc'}])
        self.assertEqual(plan['unknown'], {})

    def test_formulas_are_preserved(self):
        rows = [['Home team', 'Away team'], ['Arsenal', 'Tottenham Hotspur']]
        plan = preview(rows, self.mappings, formulas=[rows[0], ['=LOOKUP(A2)', 'Tottenham Hotspur']])
        self.assertEqual(plan['formula_cells_skipped'], ['I2'])
        self.assertEqual([c['cell'] for c in plan['changes']], ['J2'])

    def test_wrong_headers_stop_preview(self):
        with self.assertRaises(ValueError):
            preview([['Price', 'Quantity']], self.mappings)


if __name__ == '__main__':
    unittest.main()
