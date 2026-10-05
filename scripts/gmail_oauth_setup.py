"""One-time helper: obtain a Gmail OAuth refresh token for the tracker.

Prerequisite (done once in Google Cloud Console while signed in as the mailbox owner):
  1. Create a project (any name), enable the "Gmail API".
  2. OAuth consent screen -> User type "Internal" (works for Google Workspace accounts such as
     ucdavis.edu and needs no Google verification). Add scope https://mail.google.com/ .
  3. Credentials -> Create credentials -> OAuth client ID -> Application type "Desktop app".
     Copy the client ID and client secret.

Then run:
    python scripts/gmail_oauth_setup.py --client-id ... --client-secret ...
A browser window opens; sign in with the mailbox account and approve. The script prints the
three values to store as GitHub Actions secrets: GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET,
GMAIL_REFRESH_TOKEN (plus GMAIL_USER = the mailbox address). Nothing is written to disk.
"""
from __future__ import annotations

import argparse
import http.server
import secrets
import threading
import urllib.parse
import webbrowser

import requests

SCOPE = "https://mail.google.com/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    redirect = f"http://localhost:{args.port}/"
    state = secrets.token_urlsafe(16)
    got: dict = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                got["code"] = q["code"][0]
                body = b"Authorized. You can close this window."
            else:
                body = b"Missing or invalid code."
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):  # silence
            pass

    srv = http.server.HTTPServer(("localhost", args.port), Handler)
    threading.Thread(target=srv.handle_request, daemon=True).start()

    url = AUTH_URL + "?" + urllib.parse.urlencode({
        "client_id": args.client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    print("Opening browser for Google sign-in. If it does not open, visit:\n", url)
    webbrowser.open(url)
    srv.server_close() if False else None
    while "code" not in got:
        pass
    r = requests.post(TOKEN_URL, data={
        "code": got["code"],
        "client_id": args.client_id,
        "client_secret": args.client_secret,
        "redirect_uri": redirect,
        "grant_type": "authorization_code",
    }, timeout=30)
    r.raise_for_status()
    tok = r.json()
    if "refresh_token" not in tok:
        raise SystemExit("No refresh token returned; remove the app under myaccount.google.com/permissions and rerun.")
    print("\nAdd these as repository secrets (Settings -> Secrets and variables -> Actions):")
    print("  GMAIL_USER           = <the mailbox address>")
    print(f"  GMAIL_CLIENT_ID      = {args.client_id}")
    print(f"  GMAIL_CLIENT_SECRET  = {args.client_secret}")
    print(f"  GMAIL_REFRESH_TOKEN  = {tok['refresh_token']}")


if __name__ == "__main__":
    main()
