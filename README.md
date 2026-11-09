# DagvSheet Agent

## Website dashboard

The separate, read-only buying dashboard is implemented in `website.py`,
`orders.py`, and `dashboard/`. It lists each Grove Orders row individually,
with match/section/allocation filters and order totals. Deployment files target
the user's existing Railway subscription; see RAILWAY.md. No website deployment
has been performed yet. Google browser authorization on the deployed domain is
still required. The older Mac download is a connection starter, not this website.

The dashboard uses the signed-in user's read-only access. It does not edit cells
or invoke the manual team-mapping writer. Order data is not served before sign-in.

First milestone: securely authorize Google and preview the selected private tab.
The browser starter requests read-only Google access. The cloud service-account
workflow additionally supports explicitly approved team-name replacements with
an audit trail. No AI model or automatic background schedule is configured.

The cloud service-account workflow also has saved lowercase team mappings and
a non-writing replacement preview. See SERVICE_ACCOUNT.md, team-mappings.json,
team_preview.py, and team_apply.py. The writer requires an explicit `--apply`;
do not run it automatically during setup or without user authorization.

## Run

Python 3.12 or newer is the only dependency. No installation or build is needed.

```sh
cd /workspace/dagvsheet
python app.py
```

The default bind address is loopback, port 8000. For a hosted instance, put an
HTTPS reverse proxy in front of the app; set `APP_BASE_URL` to the public HTTPS
origin and set `HOST=0.0.0.0` only when needed by the host. Set `PORT` as needed.
The host must support a long-running Python process. The built-in HTTP server is
for this development milestone; use a production application server before a
public production deployment. Do not expose the development server directly.

Credentials are loaded from `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` if both
are present. Otherwise, `GOOGLE_CREDENTIALS_FILE` points to a JSON file containing
`client_id` and `client_secret`; the existing workspace default is
`/workspace/.dagvsheet/google-oauth.json`. Keep this file outside Git with mode
0600. The repository contains no credential values. To use the app on another
machine, supply credentials through that machine's secure settings.

`GOOGLE_SHEET_ID` and `GOOGLE_SHEET_GID` select the spreadsheet and numeric tab
ID. Defaults select the spreadsheet supplied in this conversation, tab
2038894540. The preview reads only A1:AZ200. The first returned row is displayed
as a header. This is a preview, not a full-sheet import.

## Finish Google authorization

1. Enable the Google Sheets API and add your Google account as an OAuth test user.
2. Decide where this app will run. The user's browser must be able to reach it.
3. Set `APP_BASE_URL` to the app's actual origin. In the Google web OAuth client,
   register that exact origin followed by `/oauth/callback` under **Authorized
   redirect URIs**. A JavaScript origin is not required for this server-side flow.
4. Start the server and select **Connect with Google** in the app. Sign in as the
   test user with access to the sheet, approve read-only access, and verify that
   the correct tab and real rows appear.

Sessions and Google access tokens are stored only in server memory. Tokens are
browser-specific, never returned to JavaScript, and expire; reconnect when they
expire or after server restart. Disconnect clears the local session; Google
access can also be revoked in your Google account's third-party connections.
This version does not request or save refresh tokens. It is a single-process
development app; do not scale it across workers with separate session stores.

## Validation

```sh
python -m unittest discover -s tests -v
```

The tests cover PKCE, callback state, replay/expiry/denial, read-only scope,
browser session isolation, exact tab selection, bounded ranges, and real local
HTTP requests. Google responses in tests are mocked. Passing tests does not
prove Google authorization or sheet access. `/healthz` checks only local server
health. The real functional check is successful sign-in and reading the target
tab.

Required outbound domains: `accounts.google.com`, `oauth2.googleapis.com`, and
`sheets.googleapis.com`. The Google settings and running environment's applied
network policy are separate; draft changes must be applied before remote reads
can work.
