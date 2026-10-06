"""One-time helper: obtain a Gmail OAuth refresh token for the tracker.

Prerequisite (done once in Google Cloud Console while signed in as the mailbox owner):
  1. Create a project (any name), enable the "Gmail API".
  2. Google Auth Platform -> configure the consent screen, audience "Internal" (works for Google
     Workspace accounts such as ucdavis.edu and needs no Google verification).
  3. Clients -> Create client -> Application type "Desktop app". Copy the client ID and secret.

Then run:
    python scripts/gmail_oauth_setup.py --client-id ... --client-secret ... --out secrets.txt
A sign-in URL is printed (and opened in the default browser unless --no-browser). Sign in with the
mailbox account and approve. The four values to store as GitHub Actions secrets (GMAIL_USER,
GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN) are written to --out (or printed when
--out is omitted). Keep that file out of git.
"""
from __future__ import annotations

import argparse
import http.server
import secrets
import threading
import urllib.parse
import webbrowser
from pathlib import Path

import requests

SCOPE = "https://mail.google.com/"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--client-id", required=True)
    ap.add_argument("--client-secret", required=True)
    ap.add_argument("--user", default="", help="mailbox address (written to the output as GMAIL_USER)")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--out", type=Path, default=None, help="write the secrets here instead of printing them")
    ap.add_argument("--no-browser", action="store_true")
    ap.add_argument("--login-hint", default="", help="pre-select this Google account on the sign-in page")
    args = ap.parse_args()

    redirect = f"http://localhost:{args.port}/"
    state = secrets.token_urlsafe(16)
    got: dict = {}
    done = threading.Event()

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if q.get("state", [""])[0] == state and "code" in q:
                got["code"] = q["code"][0]
                body = b"Authorized. You can close this window."
            else:
                got["error"] = q.get("error", ["missing code"])[0]
                body = b"Authorization failed: " + got["error"].encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(body)
            done.set()

        def log_message(self, *a):  # silence
            pass

    srv = http.server.HTTPServer(("localhost", args.port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    params = {
        "client_id": args.client_id,
        "redirect_uri": redirect,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    if args.login_hint:
        params["login_hint"] = args.login_hint
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Sign-in URL:\n" + url + "\n", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    print("Waiting for the browser to return to localhost ...", flush=True)
    if not done.wait(timeout=600):
        raise SystemExit("Timed out waiting for authorization.")
    srv.shutdown()
    if "error" in got:
        raise SystemExit("Authorization failed: " + got["error"])

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

    lines = [
        f"GMAIL_USER={args.user or '<the mailbox address>'}",
        f"GMAIL_CLIENT_ID={args.client_id}",
        f"GMAIL_CLIENT_SECRET={args.client_secret}",
        f"GMAIL_REFRESH_TOKEN={tok['refresh_token']}",
    ]
    if args.out:
        args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"Refresh token obtained. Secrets written to {args.out} - add them as repository secrets "
              "(Settings -> Secrets and variables -> Actions), then delete the file.")
    else:
        print("\nAdd these as repository secrets (Settings -> Secrets and variables -> Actions):")
        print("\n".join("  " + l for l in lines))


if __name__ == "__main__":
    main()
