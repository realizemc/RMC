"""Sends the daily report by email via Gmail SMTP.

Credentials are never stored in this repo or in config.yaml. They're read
from environment variables at send time:

  GMAIL_SENDER_ADDRESS   the Gmail address to send FROM (can be the same
                          address you're sending TO -- "email yourself a
                          report" is the normal use case here)
  GMAIL_APP_PASSWORD     a 16-character Google "App Password" -- NOT your
                          normal Gmail password. Generate one at
                          https://myaccount.google.com/apppasswords
                          (requires 2-Step Verification to be enabled).

If those aren't set, send_email raises NotifierError with instructions
rather than silently failing or crashing the whole scan.
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage


class NotifierError(Exception):
    pass


def _get_credentials() -> tuple[str, str]:
    sender = os.environ.get("GMAIL_SENDER_ADDRESS")
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not sender or not password:
        raise NotifierError(
            "Email not sent: GMAIL_SENDER_ADDRESS and/or GMAIL_APP_PASSWORD "
            "environment variables are not set. See README.md 'Email setup' "
            "for how to generate a Google App Password."
        )
    return sender, password


def send_email(subject: str, body: str, to_addr: str) -> None:
    """Raises NotifierError on missing credentials or SMTP failure."""
    sender, password = _get_credentials()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_addr
    msg.set_content(body)

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as server:
            server.login(sender, password)
            server.send_message(msg)
    except smtplib.SMTPException as e:
        raise NotifierError(f"Failed to send email via Gmail SMTP: {e}") from e
    except OSError as e:
        raise NotifierError(f"Could not reach smtp.gmail.com: {e}") from e
