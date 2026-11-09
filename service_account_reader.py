"""Read the Live Import tab using the explicitly shared Google service account.

This helper never writes cells. Raw row values and credentials are not printed.
"""
import json
import os
import sys

from google.auth.transport.requests import AuthorizedSession
from google.oauth2 import service_account

from app import DEFAULT_SHEET, SCOPE

EXPECTED_ACCOUNT = 'dagvsheet-agent@dagvsheet-agent.iam.gserviceaccount.com'
TOKEN_URI = 'https://oauth2.googleapis.com/token'
LIVE_IMPORT_GID = 2038894540


def credentials_from_environment(*, scopes=None):
    raw = os.environ.get('GOOGLE_SERVICE_ACCOUNT_JSON')
    if not raw:
        raise ValueError('GOOGLE_SERVICE_ACCOUNT_JSON is missing. Enter the service account JSON key through environment settings.')
    try:
        info = json.loads(raw)
    except ValueError:
        raise ValueError('GOOGLE_SERVICE_ACCOUNT_JSON is not valid JSON.') from None
    if not isinstance(info, dict) or info.get('type') != 'service_account' or info.get('client_email') != EXPECTED_ACCOUNT:
        raise ValueError('The configured key must belong to the shared dagvsheet-agent service account.')
    if info.get('token_uri') != TOKEN_URI:
        raise ValueError('The configured key must use the official Google token endpoint.')
    try:
        return service_account.Credentials.from_service_account_info(info, scopes=scopes or [SCOPE])
    except Exception:
        raise ValueError('The service account signing key could not be loaded.') from None


def read_live_import(session, sheet_id=DEFAULT_SHEET):
    # Constant Google destination; a credential file cannot redirect the key to another host.
    url = 'https://sheets.googleapis.com/v4/spreadsheets/' + sheet_id
    response = session.get(url, params={
        'ranges': "'Live import'!A1:AZ200",
        'includeGridData': 'true',
        'fields': 'properties(title),sheets(properties(sheetId,title),data(startRow,rowData(values(formattedValue))))',
    }, timeout=30)
    if response.status_code != 200:
        raise ValueError(f'Google Sheets returned HTTP {response.status_code}. Check sharing, API enablement, network access, and the exact Live Import tab name.')
    payload = response.json()
    sheets = payload.get('sheets', [])
    if len(sheets) != 1 or sheets[0].get('properties', {}).get('sheetId') != LIVE_IMPORT_GID:
        raise ValueError('Google did not return the expected Live Import tab.')
    tab = sheets[0]
    rows = []
    for grid in tab.get('data', []):
        for row in grid.get('rowData', []):
            rows.append([cell.get('formattedValue', '') for cell in row.get('values', [])])
    return {'title': payload.get('properties', {}).get('title', ''), 'tab': tab['properties']['title'], 'rows': rows}


def main():
    credentials = credentials_from_environment()
    with AuthorizedSession(credentials) as session:
        data = read_live_import(session)
    # Report only dimensions; inspect headers in a later authorized task, not financial row values.
    print(json.dumps({'connected': True, 'tab': data['tab'], 'rows_read': len(data['rows']), 'columns_read': max((len(row) for row in data['rows']), default=0), 'read_only': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        if isinstance(error, ValueError):
            print(str(error), file=sys.stderr)
        else:
            print('Could not authenticate or reach Google. No sheet cells were changed.', file=sys.stderr)
        sys.exit(1)
