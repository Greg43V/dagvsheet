"""Railway website. Read-only, Google-authorized access per browser session."""
import os
import time
from flask import Flask, g, jsonify, redirect, request, send_from_directory

from app import App, ConnectionError, ROOT, google_json
from orders import read_orders


def create_website(connection=None):
    origin = os.getenv('APP_BASE_URL')
    if connection is None and not origin:
        raise RuntimeError('Set APP_BASE_URL to the website HTTPS origin (or your local development origin).')
    connection = connection or App(origin)
    site = Flask(__name__, static_folder=None)
    site.config['MAX_CONTENT_LENGTH'] = 4096

    @site.before_request
    def identify_browser():
        if request.path != '/healthz':
            g.sid, g.browser = connection.session(request.headers.get('Cookie'))

    @site.after_request
    def private_response(response):
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
        if hasattr(g, 'sid'):
            response.set_cookie('dagvsheet', g.sid, max_age=28800, httponly=True,
                                secure=connection.base_url.startswith('https:'), samesite='Lax')
        return response

    @site.get('/healthz')
    def health():
        return jsonify(status='ok')

    @site.get('/')
    def home():
        return send_from_directory(ROOT / 'dashboard', 'index.html')

    @site.get('/dashboard.css')
    @site.get('/dashboard.js')
    def assets():
        return send_from_directory(ROOT / 'dashboard', request.path[1:])

    @site.get('/api/status')
    def status():
        return jsonify(connected=bool(g.browser.get('token')) and g.browser.get('token_expires', 0) > time.time(),
                       error=g.browser.pop('error', None))

    @site.get('/connect')
    def connect():
        return redirect(connection.authorize(g.browser), code=303)

    @site.get('/oauth/callback')
    def callback():
        try:
            connection.finish(g.browser, request.args.to_dict(flat=False))
        except ConnectionError as error:
            g.browser['error'] = str(error)
        return redirect('/', code=303)

    @site.get('/api/orders')
    def orders():
        if not g.browser.get('token') or g.browser.get('token_expires', 0) <= time.time():
            g.browser.pop('token', None)
            return jsonify(error='Sign in with Google to view your orders.', code='sign_in_required'), 401
        token = g.browser['token']
        return jsonify(read_orders(lambda url: google_json(url, token=token), spreadsheet_id=connection.sheet_id))

    @site.post('/disconnect')
    def disconnect():
        if request.headers.get('Origin') != connection.base_url:
            return jsonify(error='Request origin denied.'), 403
        g.browser.clear()
        g.browser['expires'] = time.time() + 28800
        return jsonify(disconnected=True)

    @site.errorhandler(ConnectionError)
    def google_error(error):
        return jsonify(error=str(error)), 400

    @site.errorhandler(500)
    def unexpected_error(_):
        return jsonify(error='The website could not complete this request. Please try again.'), 500

    return site


# Gunicorn invokes the factory, so importing this module in tests needs no secrets.
