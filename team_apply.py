"""Explicitly apply an approved team mapping, keeping an audit for undo.

Uses exact, per-cell find/replace requests, so a cell changed since the preview
is not blindly overwritten. Formula cells are excluded by Google as well.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import uuid

from google.auth.transport.requests import AuthorizedSession

from app import DEFAULT_SHEET
from service_account_reader import LIVE_IMPORT_GID, credentials_from_environment
from team_mapping import load_mappings, normalize
from team_preview import build_live_preview, read_team_rows

WRITE_SCOPE = 'https://www.googleapis.com/auth/spreadsheets'


def make_requests(plan):
    if plan['spreadsheet_id'] != DEFAULT_SHEET or plan['sheet_id'] != LIVE_IMPORT_GID:
        raise ValueError('Preview targets an unexpected spreadsheet or tab.')
    mappings = load_mappings()
    requests, seen = [], set()
    for change in plan['changes']:
        cell, before, after = change['cell'], change['before'], change['after']
        match = re.fullmatch(r'([IJ])([1-9][0-9]*)', cell)
        if not match or int(match[2]) < 2 or cell in seen:
            raise ValueError('Preview contains an invalid or repeated team cell.')
        if not isinstance(before, str) or before.startswith('=') or mappings.get(normalize(before)) != after or before == after:
            raise ValueError('Preview contains a change outside the saved preferences.')
        seen.add(cell)
        row, column = int(match[2]) - 1, 8 if match[1] == 'I' else 9
        requests.append({'findReplace': {
            'find': before, 'replacement': after,
            'range': {'sheetId': LIVE_IMPORT_GID, 'startRowIndex': row, 'endRowIndex': row + 1,
                      'startColumnIndex': column, 'endColumnIndex': column + 1},
            'matchCase': True, 'matchEntireCell': True,
            'searchByRegex': False, 'includeFormulas': False,
        }})
    return requests


def save_audit(path, value, *, exclusive=False):
    flags = os.O_WRONLY | os.O_CREAT | (os.O_EXCL if exclusive else os.O_TRUNC)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def verify_changes(changes, rows):
    mismatches = []
    for change in changes:
        index = int(change['cell'][1:]) - 1
        column = 0 if change['cell'][0] == 'I' else 1
        value = rows[index][column] if index < len(rows) and column < len(rows[index]) else ''
        if value != change['after']:
            mismatches.append(change['cell'])
    return mismatches


def apply_live(session, *, audit_directory=Path('/workspace/.dagvsheet/team-change-history')):
    plan = build_live_preview(session)
    requests = make_requests(plan)
    if not requests:
        return {'status': 'no_changes_needed', 'cells_changed': 0, 'unknown': plan['unknown']}
    # Refresh immediately before writing; stop if rows, values, or mapping file changed.
    current = build_live_preview(session)
    if current['changes'] != plan['changes'] or current['mappings_sha256'] != plan['mappings_sha256']:
        raise ValueError('The sheet or mappings changed during the preview. Stopped without writing.')
    audit_directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    audit = audit_directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8] + '.json')
    record = {'status': 'prepared', 'plan': plan}
    save_audit(audit, record, exclusive=True)
    try:
        response = session.post('https://sheets.googleapis.com/v4/spreadsheets/' + DEFAULT_SHEET + ':batchUpdate',
                                json={'requests': requests}, timeout=60)
        if response.status_code != 200:
            record['status'] = 'request_failed'
            record['http_status'] = response.status_code
            save_audit(audit, record)
            raise ValueError(f'Google returned HTTP {response.status_code}. Audit saved; inspect before retrying.')
        result = response.json()
        replies = [item.get('findReplace', {}) for item in result.get('replies', [])]
        changed = sum(item.get('valuesChanged', 0) for item in replies)
        record.update(status='written_verification_pending', cells_changed=changed,
                      formulas_changed=sum(item.get('formulasChanged', 0) for item in replies))
        save_audit(audit, record)
        _, rows = read_team_rows(session)
        mismatches = verify_changes(plan['changes'], rows)
        complete = changed == len(requests) and not mismatches and record['formulas_changed'] == 0
        record.update(status='verified' if complete else 'needs_review', verification_mismatches=mismatches,
                      completed_at=datetime.now(timezone.utc).isoformat())
        save_audit(audit, record)
        return {'status': record['status'], 'cells_changed': changed,
                'rows_targeted': len({c['cell'][1:] for c in plan['changes']}),
                'formulas_changed': record['formulas_changed'], 'verification_mismatches': mismatches,
                'unknown_left_unchanged': plan['unknown'], 'audit_file': str(audit)}
    except Exception:
        # Never repeat a request automatically after an uncertain network outcome.
        if record['status'] == 'prepared':
            record['status'] = 'outcome_unconfirmed'
            save_audit(audit, record)
        raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Apply saved team mappings after approval.')
    parser.add_argument('--apply', action='store_true', required=True)
    parser.parse_args()
    try:
        with AuthorizedSession(credentials_from_environment(scopes=[WRITE_SCOPE])) as session:
            result = apply_live(session)
        print(json.dumps(result, indent=2))
        if result['status'] == 'needs_review':
            sys.exit(1)
    except Exception as error:
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print('The live operation could not complete. Inspect the audit before retrying.', file=sys.stderr)
        sys.exit(1)
