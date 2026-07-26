import os
import unittest
from unittest.mock import MagicMock, patch

from src.notifier import NotifierError, send_email


class TestNotifier(unittest.TestCase):
    def test_raises_when_credentials_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")

    def test_raises_when_only_one_credential_set(self):
        with patch.dict(os.environ, {"GMAIL_SENDER_ADDRESS": "me@gmail.com"}, clear=True):
            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")

    def test_sends_via_smtp_when_credentials_present(self):
        env = {"GMAIL_SENDER_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "app-pass"}
        with patch.dict(os.environ, env, clear=True), patch("smtplib.SMTP_SSL") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            send_email("hello", "world", "to@example.com")

            mock_smtp_cls.assert_called_once_with("smtp.gmail.com", 465, timeout=30)
            mock_server.login.assert_called_once_with("me@gmail.com", "app-pass")
            self.assertTrue(mock_server.send_message.called)
            sent_msg = mock_server.send_message.call_args[0][0]
            self.assertEqual(sent_msg["Subject"], "hello")
            self.assertEqual(sent_msg["From"], "me@gmail.com")
            self.assertEqual(sent_msg["To"], "to@example.com")

    def test_sends_multipart_when_html_body_given(self):
        env = {"GMAIL_SENDER_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "app-pass"}
        with patch.dict(os.environ, env, clear=True), patch("smtplib.SMTP_SSL") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            send_email("hello", "plain text", "to@example.com", html_body="<b>rich</b>")

            sent_msg = mock_server.send_message.call_args[0][0]
            self.assertTrue(sent_msg.is_multipart())
            plain_part = sent_msg.get_body(preferencelist=("plain",))
            html_part = sent_msg.get_body(preferencelist=("html",))
            self.assertIn("plain text", plain_part.get_content())
            self.assertIn("<b>rich</b>", html_part.get_content())

    def test_wraps_smtp_exceptions(self):
        import smtplib
        env = {"GMAIL_SENDER_ADDRESS": "me@gmail.com", "GMAIL_APP_PASSWORD": "app-pass"}
        with patch.dict(os.environ, env, clear=True), patch("smtplib.SMTP_SSL") as mock_smtp_cls:
            mock_server = MagicMock()
            mock_server.login.side_effect = smtplib.SMTPAuthenticationError(535, b"bad creds")
            mock_smtp_cls.return_value.__enter__.return_value = mock_server

            with self.assertRaises(NotifierError):
                send_email("subject", "body", "to@example.com")


if __name__ == "__main__":
    unittest.main()
