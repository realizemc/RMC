#!/usr/bin/env python3
"""One-time setup: authorizes this app to send Gmail via OAuth2 and prints
the environment variables `src/notifier.py` needs.

Run this on a machine with a real browser -- NOT inside a Claude Code
sandbox, since it needs to complete an interactive Google login.

Prereqs (Google Cloud Console, https://console.cloud.google.com):
  1. Create a project (or reuse one).
  2. APIs & Services > Library: enable the "Gmail API".
  3. APIs & Services > Credentials > Create Credentials > OAuth client ID.
     Application type: "Desktop app".
  4. Note the Client ID and Client Secret it gives you.
  5. If the OAuth consent screen is in "Testing" publishing status, add the
     sending Gmail address under "Test users" or the consent screen will
     reject it.

Usage:
  python scripts/gmail_oauth_setup.py --client-id ID --client-secret SECRET
"""
from __future__ import annotations

import argparse
import http.server
import threading
import urllib.parse
import webbrowser

import requests

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SCOPE = "https://www.googleapis.com/auth/gmail.send"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/"


def _wait_for_auth_code() -> str:
    code_holder: dict[str, str] = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            code = params.get("code", [None])[0]
            if code:
                code_holder["code"] = code
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Authorized. You can close this tab and return to the terminal.")

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("localhost", REDIRECT_PORT), Handler)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    thread.join(timeout=180)
    server.server_close()
    if "code" not in code_holder:
        raise SystemExit("Timed out waiting for Google's redirect. Run the script again.")
    return code_holder["code"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--client-id", required=True)
    p.add_argument("--client-secret", required=True)
    args = p.parse_args()

    auth_params = {
        "client_id": args.client_id,
        "redirect_uri": REDIRECT_URI,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"
    print(f"Opening browser to authorize -- if it doesn't open, visit:\n{url}\n")
    webbrowser.open(url)

    code = _wait_for_auth_code()

    resp = requests.post(
        TOKEN_URL,
        data={
            "code": code,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise SystemExit(
            "No refresh_token in the response -- Google only issues one on "
            "the first consent for a given client. Revoke this app's access "
            "at https://myaccount.google.com/permissions and re-run this "
            "script."
        )

    print("\nSuccess. Set these wherever `python main.py daily` runs "
          "(shell profile, or Claude Code environment variables for "
          "scheduled runs):\n")
    print(f'  export GMAIL_SENDER_ADDRESS="youraddress@gmail.com"')
    print(f'  export GMAIL_OAUTH_CLIENT_ID="{args.client_id}"')
    print(f'  export GMAIL_OAUTH_CLIENT_SECRET="{args.client_secret}"')
    print(f'  export GMAIL_OAUTH_REFRESH_TOKEN="{refresh_token}"')


if __name__ == "__main__":
    main()
