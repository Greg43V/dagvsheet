"""Local launcher: credentials stay on the computer running this script."""
import argparse
import getpass
import json
import os
from pathlib import Path
import sys
import threading
import webbrowser

from app import App, ROOT, ThreadingHTTPServer, load_credentials, make_handler

BASE_URL = 'http://localhost:8000'


def configure_credentials():
    if os.getenv('GOOGLE_CLIENT_ID') and os.getenv('GOOGLE_CLIENT_SECRET'):
        return load_credentials()
    path = Path(os.getenv('GOOGLE_CREDENTIALS_FILE', str(Path.home() / '.dagvsheet' / 'google-oauth.json'))).expanduser()
    if not path.is_file():
        defaults_file = ROOT / 'local-client.json'
        defaults = json.loads(defaults_file.read_text()) if defaults_file.is_file() else {}
        client_id = defaults.get('client_id') or input('Google OAuth client ID: ').strip()
        print('Enter the Google client secret below. It will not appear as you type.')
        client_secret = getpass.getpass('Client secret: ').strip()
        if not client_id or not client_secret:
            raise ValueError('Both the client ID and client secret are required.')
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Exclusive creation preserves any existing file, including one created concurrently.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as stream:
            json.dump({'client_id': client_id, 'client_secret': client_secret}, stream)
        print('Saved credentials locally in your home folder under .dagvsheet.')
    os.environ['GOOGLE_CREDENTIALS_FILE'] = str(path)
    return load_credentials()


def main():
    parser = argparse.ArgumentParser(description='Start DagvSheet on your own computer.')
    parser.add_argument('--check', action='store_true', help='Validate configuration without opening a browser or starting a server.')
    parser.add_argument('--no-browser', action='store_true', help='Start without opening the browser automatically.')
    args = parser.parse_args()
    if sys.version_info < (3, 12):
        raise RuntimeError('Install Python 3.12 or newer from python.org, then run this launcher again.')
    credentials = configure_credentials()
    app = App(BASE_URL, credentials=credentials)
    print('Google redirect URI: ' + app.callback)
    if args.check:
        print('Configuration valid. This does not verify Google access.')
        return
    try:
        server = ThreadingHTTPServer(('127.0.0.1', 8000), make_handler(app))
    except OSError:
        raise RuntimeError('Port 8000 is already in use. Close the other app or an earlier DagvSheet window and try again.') from None
    print('DagvSheet is running locally. Leave this Terminal window open.')
    print('If Google reports redirect_uri_mismatch, add the redirect URI above to your OAuth web client.')
    if not args.no_browser:
        timer = threading.Timer(0.5, webbrowser.open, args=(BASE_URL,))
        timer.daemon = True
        timer.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nDagvSheet stopped.')
    finally:
        server.server_close()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, json.JSONDecodeError) as error:
        print('Could not start DagvSheet: ' + str(error), file=sys.stderr)
        sys.exit(1)
