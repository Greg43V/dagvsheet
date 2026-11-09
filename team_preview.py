"""Read all home/away cells and save a review plan, without changing the sheet."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote

from google.auth.transport.requests import AuthorizedSession

from app import DEFAULT_SHEET
from service_account_reader import LIVE_IMPORT_GID, credentials_from_environment
from team_mapping import MAPPINGS_FILE, load_mappings, preview


def read_team_rows(session):
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + DEFAULT_SHEET
    metadata = session.get(base, params={'fields': 'sheets(properties(sheetId,title))'}, timeout=30)
    if metadata.status_code != 200:
        raise ValueError('Cannot read spreadsheet metadata. No cells were changed.')
    tabs = [s['properties'] for s in metadata.json().get('sheets', []) if s.get('properties', {}).get('sheetId') == LIVE_IMPORT_GID]
    if len(tabs) != 1:
        raise ValueError('The selected team-import tab was not found.')
    title = tabs[0]['title']
    span = "'" + title.replace("'", "''") + "'!I1:J"
    response = session.get(base + '/values/' + quote(span, safe=''),
                           params={'valueRenderOption': 'FORMULA'}, timeout=30)
    if response.status_code != 200:
        raise ValueError('Cannot read home/away columns. No cells were changed.')
    rows = response.json().get('values', [])
    return title, rows


def build_live_preview(session):
    title, rows = read_team_rows(session)
    # Reading formulas lets us preserve calculated cells instead of overwriting them.
    plan = preview(rows, load_mappings(), formulas=rows)
    return {**plan, 'spreadsheet_id': DEFAULT_SHEET, 'sheet_id': LIVE_IMPORT_GID,
            'tab': title, 'generated_at': datetime.now(timezone.utc).isoformat(),
            'mappings_sha256': hashlib.sha256(MAPPINGS_FILE.read_bytes()).hexdigest()}


def main():
    with AuthorizedSession(credentials_from_environment()) as session:
        plan = build_live_preview(session)
    target = Path('/workspace/.dagvsheet/team-replacement-preview.json')
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(plan, stream, indent=2)
        stream.write('\n')
    by_target = Counter(c['after'] for c in plan['changes'])
    print(json.dumps({'data_rows_scanned': plan['data_rows_scanned'],
                      'cells_to_change': len(plan['changes']),
                      'rows_to_change': len({c['cell'][1:] for c in plan['changes']}),
                      'changes_by_preferred_name': dict(sorted(by_target.items())),
                      'unknown': plan['unknown'], 'formula_cells_skipped': plan['formula_cells_skipped'],
                      'sheet_modified': False}, indent=2))


if __name__ == '__main__':
    main()
