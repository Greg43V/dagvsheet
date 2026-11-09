"""Saved team-name preferences and a non-writing replacement preview."""
from collections import Counter
import json
from pathlib import Path

MAPPINGS_FILE = Path(__file__).with_name('team-mappings.json')


def normalize(name):
    return str(name).strip().casefold()


def load_mappings(path=MAPPINGS_FILE):
    raw = json.loads(Path(path).read_text())['mappings']
    mappings = {}
    for name, replacement in raw.items():
        if not isinstance(replacement, str) or not replacement or replacement != replacement.strip().lower():
            raise ValueError('Every replacement must be nonempty lowercase text without surrounding spaces.')
        key = normalize(name)
        if key in mappings and mappings[key] != replacement:
            raise ValueError('Conflicting team mappings.')
        mappings[key] = replacement
    # Previously converted codes remain stable when checked on a later run.
    for value in list(mappings.values()):
        if value in mappings and mappings[value] != value:
            raise ValueError('A preferred code conflicts with another team mapping.')
        mappings[value] = value
    return mappings


def preview(rows, mappings, formulas=None):
    if not rows or [normalize(v) for v in rows[0]] != ['home team', 'away team']:
        raise ValueError('Home/away column headers do not match. Nothing should be changed.')
    changes, unknown, formula_cells = [], Counter(), []
    for row_index, row in enumerate(rows[1:], start=2):
        for offset, value in enumerate(row[:2]):
            if not normalize(value):
                continue
            # User-designated placeholders in the first data row (sheet row 2).
            if row_index == 2 and normalize(value) == 'x':
                continue
            cell = ('I' if offset == 0 else 'J') + str(row_index)
            source = formulas[row_index - 1] if formulas and row_index - 1 < len(formulas) else []
            if offset < len(source) and str(source[offset]).startswith('='):
                formula_cells.append(cell)
                continue
            replacement = mappings.get(normalize(value))
            if replacement is None:
                unknown[str(value)] += 1
            elif value != replacement:
                changes.append({'cell': cell, 'before': value, 'after': replacement})
    return {'changes': changes, 'unknown': dict(unknown), 'formula_cells_skipped': formula_cells,
            'data_rows_scanned': len(rows) - 1}
