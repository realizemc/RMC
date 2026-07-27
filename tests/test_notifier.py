import base64
import os
import unittest
from unittest.mock import MagicMock, patch

import requests

from src.notifier import NotifierError, send_email

ENV = {
    "GMAIL_SENDER_ADDRESS": "me@gmail.com",
    "GMAIL_OAUTH_CLIENT_ID": "client-id",
    "GMAIL_OAUTH_CLIENT_SECRET": "client-secret",
    "GMAIL_OAUTH_REFRESH_TOKEN": "refresh-token",
}


def _mock_token_response():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = {"access_token": "fake-access-token"}
    return resp


def _mock_send_response():
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    return resp


class TestNotifier(unittest.TestCase):
    def test_raises_when_credentials_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")

    def test_raises_when_credentials_incomplete(self):
        with patch.dict(os.environ, {"GMAIL_SENDER_ADDRESS": "me@gmail.com"}, clear=True):
            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")

    def test_sends_via_gmail_api_when_credentials_present(self):
        with patch.dict(os.environ, ENV, clear=True), patch("src.notifier.requests.post") as mock_post:
            mock_post.side_effect = [_mock_token_response(), _mock_send_response()]

            send_email("hello", "world", "to@example.com")

            self.assertEqual(mock_post.call_count, 2)
            token_call, send_call = mock_post.call_args_list
            self.assertEqual(token_call.args[0], "https://oauth2.googleapis.com/token")
            self.assertEqual(send_call.args[0], "https://gmail.googleapis.com/gmail/v1/users/me/messages/send")
            self.assertEqual(send_call.kwargs["headers"]["Authorization"], "Bearer fake-access-token")

            raw = send_call.kwargs["json"]["raw"]
            decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
            self.assertIn(b"Subject: hello", decoded)
            self.assertIn(b"From: me@gmail.com", decoded)
            self.assertIn(b"To: to@example.com", decoded)

    def test_sends_multipart_when_html_body_given(self):
        with patch.dict(os.environ, ENV, clear=True), patch("src.notifier.requests.post") as mock_post:
            mock_post.side_effect = [_mock_token_response(), _mock_send_response()]

            send_email("hello", "plain text", "to@example.com", html_body="<b>rich</b>")

            send_call = mock_post.call_args_list[1]
            raw = send_call.kwargs["json"]["raw"]
            decoded = base64.urlsafe_b64decode(raw.encode("ascii"))
            self.assertIn(b"plain text", decoded)
            self.assertIn(b"<b>rich</b>", decoded)

    def test_wraps_token_refresh_errors(self):
        with patch.dict(os.environ, ENV, clear=True), patch("src.notifier.requests.post") as mock_post:
            mock_post.side_effect = requests.RequestException("boom")
            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")

    def test_wraps_send_errors(self):
        with patch.dict(os.environ, ENV, clear=True), patch("src.notifier.requests.post") as mock_post:
            failing_send = MagicMock()
            failing_send.raise_for_status.side_effect = requests.RequestException("boom")
            mock_post.side_effect = [_mock_token_response(), failing_send]

            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")


if __name__ == "__main__":
    unittest.main()
