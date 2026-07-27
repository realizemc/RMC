"""Sends the daily report by email via the Gmail API (REST over HTTPS).

Plain SMTP (ports 465/587) is blocked in some sandboxed environments --
e.g. Claude Code cloud sessions only allow outbound traffic on port 443 --
so this sends through Gmail's REST API instead of smtplib. It works the
same way whether `daily` runs on your own machine or in a sandbox.

Credentials are never stored in this repo or in config.yaml. They're read
from environment variables at send time:

  GMAIL_SENDER_ADDRESS       the Gmail address to send FROM
  GMAIL_OAUTH_CLIENT_ID      OAuth2 client ID
  GMAIL_OAUTH_CLIENT_SECRET  OAuth2 client secret
  GMAIL_OAUTH_REFRESH_TOKEN  long-lived refresh token

Run `python scripts/gmail_oauth_setup.py` once, on a machine with a real
browser, to obtain these -- see README.md 'Email setup'.

If those aren't set, send_email raises NotifierError with instructions
rather than silently failing or crashing the whole scan.
"""
from __future__ import annotations

import base64
import os
from email.message import EmailMessage

import requests

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class NotifierError(Exception):
    pass


def _get_credentials() -> tuple[str, str, str, str]:
    sender = os.environ.get("GMAIL_SENDER_ADDRESS")
    client_id = os.environ.get("GMAIL_OAUTH_CLIENT_ID")
    client_secret = os.environ.get("GMAIL_OAUTH_CLIENT_SECRET")
    refresh_token = os.environ.get("GMAIL_OAUTH_REFRESH_TOKEN")
    if not all([sender, client_id, client_secret, refresh_token]):
        raise NotifierError(
            "Email not sent: GMAIL_SENDER_ADDRESS, GMAIL_OAUTH_CLIENT_ID, "
            "GMAIL_OAUTH_CLIENT_SECRET and/or GMAIL_OAUTH_REFRESH_TOKEN "
            "environment variables are not set. Run "
            "`python scripts/gmail_oauth_setup.py` once to generate them "
            "-- see README.md 'Email setup'."
        )
    return sender, client_id, client_secret, refresh_token


def _get_access_token(client_id: str, client_secret: str, refresh_token: str) -> str:
    try:
        resp = requests.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise NotifierError(f"Could not refresh Gmail OAuth token: {e}") from e
    return resp.json()["access_token"]


def send_email(subject: str, body: str, to_addr: str, html_body: str | None = None) -> None:
    """Raises NotifierError on missing credentials or API failure.

    If `html_body` is given, sends a multipart email (plain text + HTML)
    so clients that render HTML show the dashboard version, and everything
    else falls back to the plain-text body.
    """
    sender, client_id, client_secret, refresh_token = _get_credentials()
    access_token = _get_access_token(client_id, client_secret, refresh_token)

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(body)
    if html_body is not None:
        msg.add_alternative(html_body, subtype="html")

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

    try:
        resp = requests.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw},
            timeout=30,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise NotifierError(f"Failed to send email via Gmail API: {e}") from e
