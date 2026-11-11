"""Read-only Live Profit figure and durable, date-deduplicated snapshots."""
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
from pathlib import Path
import os
import sqlite3
import threading
from urllib.parse import quote

from app import ConnectionError, DEFAULT_SHEET

PROFIT_GID = 1787939114
PROFIT_RANGE = 'B1'
# South Africa does not observe daylight saving time.
SAST = timezone(timedelta(hours=2), 'SAST')


def read_profit(get_json, *, spreadsheet_id=DEFAULT_SHEET):
    base = 'https://sheets.googleapis.com/v4/spreadsheets/' + quote(spreadsheet_id, safe='')
    metadata = get_json(base + '?fields=sheets(properties(sheetId,title))')
    tabs = [s['properties'] for s in metadata.get('sheets', [])
            if s.get('properties', {}).get('sheetId') == PROFIT_GID]
    if len(tabs) != 1:
        raise ConnectionError('The Live Profit tab was not found.')
    span = "'" + tabs[0]['title'].replace("'", "''") + "'!A1:B1"
    payload = get_json(base + '/values/' + quote(span, safe='') + '?valueRenderOption=UNFORMATTED_VALUE')
    rows = payload.get('values', [])
    if not rows or len(rows[0]) < 2 or str(rows[0][0]).strip().lower() != 'profit':
        raise ConnectionError('The Live Profit figure or its label has changed. Check cells A1:B1.')
    raw = rows[0][1]
    try:
        value = Decimal(str(raw))
        if isinstance(raw, bool) or not value.is_finite():
            raise InvalidOperation
    except InvalidOperation:
        raise ConnectionError('Live Profit B1 is not a valid number. No snapshot was saved.') from None
    return {'value': str(value), 'currency': 'GBP', 'tab': tabs[0]['title'],
            'cell': PROFIT_RANGE, 'fetchedAt': datetime.now(timezone.utc).isoformat()}


def scheduled_for(now):
    day = now.astimezone(SAST).date()
    kinds = []
    if day.weekday() == 0:
        kinds.append('weekly')
    if day.day == 1:
        kinds.append('monthly')
    return day.isoformat(), kinds


def next_capture(now):
    day = now.astimezone(SAST).date() + timedelta(days=1)
    while day.weekday() != 0 and day.day != 1:
        day += timedelta(days=1)
    return day.isoformat()


class SnapshotStore:
    def __init__(self, path, sheet_id=DEFAULT_SHEET):
        self.path = Path(path)
        self.sheet_id = sheet_id

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                db.execute('''CREATE TABLE IF NOT EXISTS profit_snapshots (
                    sheet_id TEXT NOT NULL, snapshot_date TEXT NOT NULL,
                    captured_at TEXT NOT NULL, kinds TEXT NOT NULL, value TEXT NOT NULL,
                    PRIMARY KEY (sheet_id, snapshot_date))''')
                yield db
        finally:
            db.close()

    def contains(self, day):
        with self.connect() as db:
            return db.execute('SELECT 1 FROM profit_snapshots WHERE sheet_id=? AND snapshot_date=?',
                              (self.sheet_id, day)).fetchone() is not None

    def save(self, now, kinds, value):
        day, expected_kinds = scheduled_for(now)
        if not kinds or kinds != expected_kinds:
            raise ValueError('Snapshots are only saved on scheduled dates.')
        with self.connect() as db:
            result = db.execute('INSERT OR IGNORE INTO profit_snapshots VALUES (?, ?, ?, ?, ?)',
                                (self.sheet_id, day, now.astimezone(timezone.utc).isoformat(),
                                 ','.join(kinds), value))
            return result.rowcount == 1

    def history(self):
        with self.connect() as db:
            rows = db.execute('SELECT * FROM profit_snapshots WHERE sheet_id=? ORDER BY snapshot_date',
                              (self.sheet_id,)).fetchall()
        result, previous, by_kind = [], None, {}
        for row in rows:
            value = Decimal(row['value'])
            delta = value - previous if previous is not None else None
            percentage = delta / abs(previous) * 100 if previous not in (None, 0) else None
            comparisons = {}
            for kind in row['kinds'].split(','):
                prior = by_kind.get(kind)
                difference = value - prior[1] if prior else None
                percent = difference / abs(prior[1]) * 100 if prior and prior[1] != 0 else None
                comparisons[kind] = {
                    'previousDate': prior[0] if prior else None,
                    'previousValue': str(prior[1]) if prior else None,
                    'change': str(difference) if difference is not None else None,
                    'changePercent': str(percent) if percent is not None else None,
                }
                by_kind[kind] = (row['snapshot_date'], value)
            result.append({'date': row['snapshot_date'], 'capturedAt': row['captured_at'],
                           'kinds': row['kinds'].split(','), 'value': str(value),
                           'comparisons': comparisons,
                           'change': str(delta) if delta is not None else None,
                           'changePercent': str(percentage) if percentage is not None else None})
            previous = value
        return list(reversed(result))


class ProfitSnapshots:
    """One scheduler in the existing single Gunicorn worker; never runs mappings."""
    def __init__(self, sheet_id, store=None, reader=None, logger=None):
        self.sheet_id = sheet_id
        self.store = store
        self.reader = reader
        self.logger = logger
        self.state = 'scheduled' if store and reader else 'setup_required'
        self.stop = threading.Event()
        self.thread = None

    def tick(self, now=None):
        live_clock = now is None
        now = now or datetime.now(timezone.utc)
        day, kinds = scheduled_for(now)
        if not self.store or not self.reader:
            return False
        if not kinds or self.store.contains(day):
            return False
        figure = self.reader()
        captured = datetime.now(timezone.utc) if live_clock else now
        # Do not assign a read that crossed local midnight to the preceding day.
        if scheduled_for(captured)[0] != day:
            return False
        return self.store.save(captured, kinds, figure['value'])

    def run(self):
        while not self.stop.is_set():
            try:
                self.tick()
                self.state = 'scheduled'
            except Exception:
                self.state = 'retrying'
                if self.logger:
                    self.logger.warning('Live Profit snapshot failed; retrying in one minute. No snapshot saved.')
            self.stop.wait(60)

    def start(self):
        if self.store and self.reader and self.thread is None:
            self.thread = threading.Thread(target=self.run, name='profit-snapshots', daemon=True)
            self.thread.start()

    def summary(self):
        return {'state': self.state, 'timezone': 'Africa/Johannesburg',
                'nextDate': next_capture(datetime.now(timezone.utc)),
                'history': self.store.history() if self.store else []}


def configured_snapshots(sheet_id, logger):
    path = os.getenv('SNAPSHOT_DB_PATH')
    if not path and os.getenv('RAILWAY_VOLUME_MOUNT_PATH'):
        path = str(Path(os.environ['RAILWAY_VOLUME_MOUNT_PATH']) / 'live-profit.sqlite3')
    store = SnapshotStore(path, sheet_id) if path else None
    reader = None
    if os.getenv('GOOGLE_SERVICE_ACCOUNT_JSON'):
        # Reuse the existing explicitly shared account and read-only scope.
        from google.auth.transport.requests import AuthorizedSession
        from service_account_reader import credentials_from_environment
        try:
            credentials = credentials_from_environment()
        except ValueError:
            logger.warning('Live Profit unattended credentials need configuration.')
        else:
            def reader():
                with AuthorizedSession(credentials) as session:
                    def get_json(url):
                        response = session.get(url, timeout=25)
                        if response.status_code != 200:
                            raise ConnectionError('Could not read Live Profit for the scheduled snapshot.')
                        return response.json()
                    return read_profit(get_json, spreadsheet_id=sheet_id)
    return ProfitSnapshots(sheet_id, store=store, reader=reader, logger=logger)
