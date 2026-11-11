# Deploy the read-only order dashboard on Railway

Railway can run the website and its backend in one service. Netlify is not
required for this version. Existing Railway plan allowances and usage pricing
still apply; no deployment has been performed by this setup task.

## What is implemented

- Google-authorized dashboard; no order data before sign-in.
- One displayed row per Grove Orders row; duplicate-looking orders are not merged.
- Match, section, allocation, order-search, and sorting controls.
- Selected-order, quantity, total-sales and weighted ticket-price totals.
- Purchase Price zero means unallocated; positive means allocated; other values
  are flagged for review. The Allocation text column does not determine status.
- Original order links and a read-only refresh button. No background writer.
- Team names use saved mappings for display only; the dashboard does not modify
  the sheet. All dates/orders are included; cancellations are not inferred.

## Railway deployment

1. Make this repository available in your GitHub account, then add a Railway
   service from that repository. Use the repository root as the service root.
   `requirements.txt`, `.python-version`, and `railway.json` configure the build
   and the Gunicorn start command. Keep one replica and one worker: sessions
   are currently stored in memory. Multiple replicas require a shared session
   store. The configured process supports four request threads.
2. Generate a Railway public domain with target port 8080, or attach your own
   domain. Add `PORT=8080` to service variables to match that routing port.
   The app starts and serves its health check even before a domain is configured.
   Google connection becomes available after a domain is configured.
3. In the Railway service's Variables, set:
   - `APP_BASE_URL`: the exact HTTPS origin, with no path. This is optional for a
     generated Railway domain: the app uses Railway's `RAILWAY_PUBLIC_DOMAIN`
     automatically. Set it explicitly when using a custom domain.
   - `GOOGLE_CLIENT_ID`: the OAuth **web application** client ID ending in
     `.apps.googleusercontent.com`.
   - `GOOGLE_CLIENT_SECRET`: the corresponding OAuth client secret.
   - Optional `GOOGLE_SHEET_ID`: the spreadsheet ID. The current spreadsheet is
     already the default.
4. In Google Auth Platform → Clients → that web client, register the exact
   `APP_BASE_URL` followed by `/oauth/callback` under Authorized redirect URIs.
   Do not include a trailing slash after callback. No JavaScript origin is
   needed. Keep the app in Testing and add authorized users as test users.
5. Deploy/redeploy. Check `/healthz`, sign in from the actual deployed domain,
   and verify the order table. The signed-in Google account must be able to
   read the spreadsheet. A successful health check is not a sign-in check.

Do not paste credentials into GitHub files or chat. Interactive views use the signed-in
user's read-only Google token. Optional unattended profit snapshots use the existing
shared service account configured securely as described below. Access tokens remain on the server and are not
returned to browser JavaScript. Users sign in again after token expiry (about an
hour), restart, or redeployment. Logs exclude URL access records to avoid recording
OAuth callback codes. A public page may load the sign-in screen; private API
responses require a valid Google-authorized session and Google sheet permission.

## Live Profit snapshots

The Live Profit view reads `Live Profit!B1` (tab ID `1787939114`), checking that A1
still says `Profit`. Browser users must sign in and retain permission to read that
source before they can see the figure or its saved history.

For unattended snapshots in the **existing Railway production service**:

1. Attach a persistent Railway volume mounted at `/data`. Set
   `SNAPSHOT_DB_PATH=/data/live-profit.sqlite3` in the service Variables. When
   omitted, the app also recognizes Railway's `RAILWAY_VOLUME_MOUNT_PATH` and
   places `live-profit.sqlite3` there. Never use ephemeral container storage for
   history. Keep volume backups enabled according to your retention needs.
2. Add `GOOGLE_SERVICE_ACCOUNT_JSON` through Railway's secure Variables UI, using
   the existing service account documented in SERVICE_ACCOUNT.md. It must contain
   the actual full JSON, not a proxy placeholder. Reuse a current saved credential;
   do not put it in source files or chat. The account must be able to read the
   spreadsheet. The scheduler requests **only the read-only Sheets scope**.
3. Apply variables and deploy the current `main`. Keep **one replica and one
   Gunicorn worker**, and turn off Railway service sleeping/serverless mode so
   the process remains available for the schedule. No separate cron service is
   needed: the existing web process checks once a minute in a background thread.
4. Sign in, open **Live Profit**, and confirm that automatic snapshots show as
   scheduled. The first capture occurs on the next Monday or month start.

The target is 00:00 **Africa/Johannesburg (SAST, UTC+2)** every Monday and on the
first of every month. If the process starts or a read recovers later on a due
date, it captures then and records the actual capture time. Failed reads retry
each minute that day. Whole missed dates are not backfilled using a later figure.
When both schedules coincide, one stored capture serves both comparisons. A
unique spreadsheet/date key prevents overwrites after restarts or duplicate ticks.

History shows each Monday against its previous saved Monday and each month start
against its previous monthly capture, with prior date/value, GBP change, and
percentage change. The first capture is a baseline; zero baselines have no
percentage. For negative baselines, percentage uses the absolute prior value.
Values are preserved at source precision and displayed as GBP to two decimals.

Missing storage or credentials leaves automatic snapshots disabled and visibly
marked as needing setup; browser-authorized figures and orders remain available.
The scheduler never imports or invokes `team_apply.py` and never writes to Sheets.
Codex environment settings and Railway production variables are separate: changing
one does not configure the other.

## Local development and verification

```sh
cd /workspace/dagvsheet
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m unittest discover -s tests -v
APP_BASE_URL=http://127.0.0.1:8010 .venv/bin/gunicorn 'website:create_website()' --bind 127.0.0.1:8010 --workers 1 --threads 4 --access-logfile /dev/null --no-control-socket
```

Use internal local requests for onboarding checks. No user-facing cloud localhost
preview is supported. Tests mock Google responses; live API validation and
deployed Google sign-in must be reported separately.
