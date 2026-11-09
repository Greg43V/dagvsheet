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
2. Generate a Railway public domain, or attach your own domain.
3. In the Railway service's Variables, set:
   - `APP_BASE_URL`: the exact HTTPS origin, with no path.
   - `GOOGLE_CLIENT_ID`: the OAuth **web application** client ID ending in
     `.apps.googleusercontent.com`.
   - `GOOGLE_CLIENT_SECRET`: the corresponding OAuth client secret.
   - Optional `GOOGLE_SHEET_ID`: the spreadsheet ID. The current spreadsheet is
     already the default. Railway supplies `PORT`; do not hard-code it.
4. In Google Auth Platform → Clients → that web client, register the exact
   `APP_BASE_URL` followed by `/oauth/callback` under Authorized redirect URIs.
   Do not include a trailing slash after callback. No JavaScript origin is
   needed. Keep the app in Testing and add authorized users as test users.
5. Deploy/redeploy. Check `/healthz`, sign in from the actual deployed domain,
   and verify the order table. The signed-in Google account must be able to
   read the spreadsheet. A successful health check is not a sign-in check.

Do not paste credentials into GitHub files or chat. The website uses the signed-in
user's read-only Google token; it does not need your service account JSON. Do not
copy that JSON into Railway. Access tokens remain on the server and are not
returned to browser JavaScript. Users sign in again after token expiry (about an
hour), restart, or redeployment. Logs exclude URL access records to avoid recording
OAuth callback codes. A public page may load the sign-in screen; private API
responses require a valid Google-authorized session and Google sheet permission.

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
