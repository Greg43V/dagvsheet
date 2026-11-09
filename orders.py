"""Read-only Grove Orders data for the buying dashboard."""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from app import ConnectionError, DEFAULT_SHEET
from team_mapping import load_mappings, normalize

GROVE_GID = 1800395594
GROVE_TITLE = 'Grove Orders'


def number(value):
    if isinstance(value, bool) or value is None or str(value).strip() == '':
        return None
    try:
        result = Decimal(str(value).replace(',', '').replace('£', '').strip())
        return float(result) if result.is_finite() else None
    except InvalidOperation:
        return None


def parse_orders(rows, *, spreadsheet_id=DEFAULT_SHEET):
    if not rows:
        raise ConnectionError('Grove Orders is empty or its headers are missing.')
    headers = {normalize(value): index for index, value in enumerate(rows[0])}
    required = ['order no', 'home team', 'away team', 'quan', 'cat', 'unit price', 'total £ price', 'purchase price', 'order id']
    if any(name not in headers for name in required):
        raise ConnectionError('The Grove Orders column headings have changed. Please check the source sheet.')
    mappings = load_mappings()
    orders = []
    for row_number, row in enumerate(rows[1:], start=2):
        def cell(name):
            index = headers[name]
            return row[index] if index < len(row) else ''
        home, away = str(cell('home team')).strip(), str(cell('away team')).strip()
        order_id = str(cell('order id')).strip()
        if not (home or away or order_id):
            continue
        price = number(cell('purchase price'))
        quantity = number(cell('quan'))
        unit, total = number(cell('unit price')), number(cell('total £ price'))
        status = 'unallocated' if price == 0 else 'allocated' if price is not None and price > 0 else 'review'
        issues = []
        if quantity is None or quantity <= 0:
            issues.append('Check quantity')
        if total is None:
            issues.append('Check total sales price')
        if status == 'review':
            issues.append('Check purchase price')
        orders.append({
            'sourceRow': row_number, 'orderNumber': str(cell('order no')).strip(),
            'orderId': order_id, 'home': mappings.get(normalize(home), home),
            'away': mappings.get(normalize(away), away),
            'section': str(cell('cat')).strip(), 'quantity': quantity,
            'unitPrice': unit, 'totalSales': total, 'purchasePrice': price,
            'status': status, 'issues': issues,
            'sourceUrl': f'https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit#gid={GROVE_GID}&range=A{row_number}:S{row_number}',
        })
    return orders


def read_orders(get_json, *, spreadsheet_id=DEFAULT_SHEET):
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + quote(spreadsheet_id, safe='')
    metadata = get_json(base + '?fields=properties(title),sheets(properties(sheetId,title))')
    tabs = [s['properties'] for s in metadata.get('sheets', []) if s.get('properties', {}).get('sheetId') == GROVE_GID]
    if len(tabs) != 1:
        raise ConnectionError('The Grove Orders tab was not found in this spreadsheet.')
    span = "'" + tabs[0]['title'].replace("'", "''") + "'!A1:S"
    data = get_json(base + '/values/' + quote(span, safe='') + '?valueRenderOption=UNFORMATTED_VALUE')
    return {'orders': parse_orders(data.get('values', []), spreadsheet_id=spreadsheet_id),
            'spreadsheet': metadata.get('properties', {}).get('title', ''),
            'tab': tabs[0]['title'], 'readOnly': True,
            'fetchedAt': datetime.now(timezone.utc).isoformat()}
