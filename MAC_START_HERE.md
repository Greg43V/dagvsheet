# Start DagvSheet on your Mac

1. In Google Cloud, open **Google Auth Platform → Clients → your DagvSheet web
   client**. Under **Authorized redirect URIs**, add exactly:

   ```text
   http://localhost:8000/oauth/callback
   ```

   Click **Save**. No JavaScript origin is needed. Allow a few minutes for Google's
   change to propagate if it initially reports `redirect_uri_mismatch`.

2. Install Python 3.12 or newer from https://www.python.org/downloads/macos/ if
   needed. Run the official installer's **Install Certificates.command** if the
   installer provides it; this configures trusted certificates for HTTPS.
   Never disable certificate verification to fix a connection problem.

3. Unzip the download. Open **Start DagvSheet.command**. If macOS blocks it,
   use Finder's Control-click → Open for this launcher after inspecting it.
   You can also open Terminal, type `cd `, drag the extracted folder into the
   Terminal window, press Return, and run `python3 launcher.py`.

4. On first launch, enter your Google OAuth client secret into Terminal when
   prompted. It will not appear as you type. This download includes your public
   client ID, but **does not include your client secret**. The launcher stores
   the secret locally in `~/.dagvsheet/google-oauth.json` with mode 0600. Do not
   share that file. To change credentials, remove that file and restart.

5. The launcher opens your browser. Click **Connect with Google**, sign in as
   the test user you added, and approve read-only access. Verify the spreadsheet
   title, tab, and rows shown in the app. Google Sheets API must be enabled, and
   that Google account must have access to the private sheet.

Leave Terminal open while using the app. Press Control-C to stop it. Tokens are
memory-only; you must sign in again after restarting or when access expires.

This version is a connection milestone. It reads only the selected sheet tab's
first 200 rows and 52 columns. It does not yet run an AI model or edit cells.

Running on your Mac uses your Mac's Internet connection; Codex's cloud network
settings are not required for this local connection.
