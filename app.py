"""DagvSheet's Google connection. Python 3.12+, no third-party dependencies."""
import base64
import hashlib
import http.cookies
import json
import os
from pathlib import Path
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
SCOPE = 'https://www.googleapis.com/auth/spreadsheets.readonly'
DEFAULT_SHEET = '1RZTx1fJYR8l5tGcPTue70xOq50qVsXWETvKPULnQV44'


class ConnectionError(Exception):
    pass


def google_json(url, *, form=None, token=None):
    headers = {'Accept': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        headers['Content-Type'] = 'application/x-www-form-urlencoded'
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        # Never expose upstream bodies: they may contain credentials or row data.
        if error.code == 401:
            raise ConnectionError('Google authorization expired. Connect again.') from None
        if error.code == 403:
            raise ConnectionError('Google access was denied. Check sheet sharing, Sheets API access, and network settings.') from None
        raise ConnectionError('Google returned an error. Please try again.') from None
    except (urllib.error.URLError, TimeoutError):
        raise ConnectionError('Cannot reach Google. Check the environment network settings.') from None


def load_credentials():
    client_id, client_secret = os.getenv('GOOGLE_CLIENT_ID'), os.getenv('GOOGLE_CLIENT_SECRET')
    if client_id and client_secret:
        return {'client_id': client_id, 'client_secret': client_secret}
    path = Path(os.getenv('GOOGLE_CREDENTIALS_FILE', '/workspace/.dagvsheet/google-oauth.json'))
    if path.is_file():
        value = json.loads(path.read_text())
        if value.get('client_id') and value.get('client_secret'):
            return value
    raise ConnectionError('Google credentials are missing from this server.')


class App:
    def __init__(self, base_url, credentials=None, sheet_id=None, gid=None):
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.path not in ('', '/') or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('APP_BASE_URL must be an origin with no path or credentials.')
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ValueError('A hosted APP_BASE_URL must use HTTPS.')
        self.base_url = base_url.rstrip('/')
        self.callback = self.base_url + '/oauth/callback'
        self.credentials = credentials
        self.sheet_id = sheet_id or os.getenv('GOOGLE_SHEET_ID', DEFAULT_SHEET)
        self.gid = int(gid if gid is not None else os.getenv('GOOGLE_SHEET_GID', '2038894540'))
        # Tokens are browser-specific and memory-only. Restarting requires sign-in again.
        self.sessions = {}
        self.lock = threading.RLock()

    def session(self, cookie):
        jar = http.cookies.SimpleCookie()
        try:
            jar.load(cookie or '')
        except http.cookies.CookieError:
            pass
        sid = jar['dagvsheet'].value if 'dagvsheet' in jar else ''
        now = time.time()
        with self.lock:
            for old in list(self.sessions):
                if self.sessions[old]['expires'] < now:
                    del self.sessions[old]
            if sid not in self.sessions:
                sid = secrets.token_urlsafe(32)
                self.sessions[sid] = {'expires': now + 8 * 3600}
            return sid, self.sessions[sid]

    def credentials_for_google(self):
        return self.credentials if self.credentials is not None else load_credentials()

    def authorize(self, session):
        credentials = self.credentials_for_google()
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip('=')
        session['oauth'] = {'state': state, 'verifier': verifier, 'created': time.time()}
        return 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
            'client_id': credentials['client_id'], 'redirect_uri': self.callback,
            'response_type': 'code', 'scope': SCOPE, 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256',
        })

    def finish(self, session, query):
        pending = session.pop('oauth', None)
        if not pending or time.time() - pending['created'] > 600 or not secrets.compare_digest(query.get('state', [''])[0], pending['state']):
            raise ConnectionError('The sign-in request expired or did not match this browser. Connect again.')
        if 'error' in query:
            raise ConnectionError('Google sign-in was cancelled or denied. You can connect again.')
        code = query.get('code', [''])[0]
        if not code:
            raise ConnectionError('Google did not supply an authorization code.')
        token = google_json('https://oauth2.googleapis.com/token', form={
            **self.credentials_for_google(), 'grant_type': 'authorization_code',
            'code': code, 'redirect_uri': self.callback, 'code_verifier': pending['verifier'],
        })
        if not token.get('access_token') or SCOPE not in token.get('scope', '').split():
            raise ConnectionError('Google did not grant the requested sheet access.')
        session['token'] = token['access_token']
        session['token_expires'] = time.time() + int(token.get('expires_in', 3600)) - 30

    def read_sheet(self, session):
        if not session.get('token') or session.get('token_expires', 0) <= time.time():
            session.pop('token', None)
            raise ConnectionError('Connect your Google account to read this sheet.')
        url = 'https://sheets.googleapis.com/v4/spreadsheets/' + urllib.parse.quote(self.sheet_id, safe='')
        metadata = google_json(url + '?fields=properties(title),sheets(properties(sheetId,title,gridProperties))', token=session['token'])
        tab = next((s['properties'] for s in metadata.get('sheets', []) if s['properties']['sheetId'] == self.gid), None)
        if tab is None:
            raise ConnectionError('The selected tab was not found in this spreadsheet.')
        # Bounded read: first 200 rows, first 52 columns; never changes the sheet.
        span = "'" + tab['title'].replace("'", "''") + "'!A1:AZ200"
        values = google_json(url + '/values/' + urllib.parse.quote(span, safe='') + '?valueRenderOption=FORMATTED_VALUE', token=session['token'])
        return {'title': metadata['properties']['title'], 'tab': tab['title'], 'rows': values.get('values', []), 'limit': 'First 200 rows and 52 columns', 'readOnly': True}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass  # OAuth codes and sheet data must not appear in access logs.

        def respond(self, status, body=b'', content_type='application/json', extra=None):
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
            if hasattr(self, 'sid'):
                cookie = f'dagvsheet={self.sid}; HttpOnly; SameSite=Lax; Path=/; Max-Age=28800'
                if app.base_url.startswith('https:'):
                    cookie += '; Secure'
                self.send_header('Set-Cookie', cookie)
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            if parsed.path == '/healthz':
                self.respond(200, b'{"status":"ok"}')
                return
            self.sid, session = app.session(self.headers.get('Cookie'))
            try:
                if parsed.path == '/':
                    self.respond(200, (ROOT / 'static/index.html').read_bytes(), 'text/html; charset=utf-8')
                elif parsed.path in ('/app.js', '/style.css'):
                    name, mime = ('app.js', 'text/javascript') if parsed.path.endswith('.js') else ('style.css', 'text/css')
                    self.respond(200, (ROOT / 'static' / name).read_bytes(), mime)
                elif parsed.path == '/api/status':
                    self.respond(200, json.dumps({'connected': bool(session.get('token')) and session.get('token_expires', 0) > time.time(), 'error': session.pop('error', None)}).encode())
                elif parsed.path == '/connect':
                    self.respond(303, extra={'Location': app.authorize(session)})
                elif parsed.path == '/oauth/callback':
                    app.finish(session, urllib.parse.parse_qs(parsed.query))
                    self.respond(303, extra={'Location': '/'})
                elif parsed.path == '/api/sheet':
                    self.respond(200, json.dumps(app.read_sheet(session)).encode())
                else:
                    self.respond(404, b'{"error":"Not found"}')
            except ConnectionError as error:
                if parsed.path == '/oauth/callback':
                    session['error'] = str(error)
                    self.respond(303, extra={'Location': '/'})
                else:
                    self.respond(400, json.dumps({'error': str(error)}).encode())
            except Exception:
                self.respond(500, b'{"error":"The server could not complete this request."}')

        def do_POST(self):
            # Same-origin checks prevent cross-site logout. No sheet-write route exists.
            if self.headers.get('Origin') != app.base_url:
                self.respond(403, b'{"error":"Request origin denied"}')
                return
            if self.path != '/disconnect':
                self.respond(404, b'{"error":"Not found"}')
                return
            self.sid, session = app.session(self.headers.get('Cookie'))
            session.clear()
            session['expires'] = time.time() + 8 * 3600
            self.respond(200, b'{"disconnected":true}')
    return Handler


if __name__ == '__main__':
    port = int(os.getenv('PORT', '8000'))
    app = App(os.getenv('APP_BASE_URL', f'http://127.0.0.1:{port}'))
    server = ThreadingHTTPServer((os.getenv('HOST', '127.0.0.1'), port), make_handler(app))
    print(f'DagvSheet server listening on port {port}. Google authorization is required to read rows.', flush=True)
    server.serve_forever()
