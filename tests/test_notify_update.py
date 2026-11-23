import unittest
from unittest.mock import patch

from notify_update import build_message, send_update_email


class UpdateNotificationTests(unittest.TestCase):
    def test_message_contains_published_report_details(self):
        payload = {
            "updated_at": "2026-11-23 15:01:02",
            "trends": [{"topic_name": "測試話題"}],
        }

        message = build_message(
            payload,
            sender="sender@gmail.com",
            recipient="recipient@example.com",
            site_url="https://kaychen46.github.io/taiwan-trend-radar/",
        )

        self.assertEqual(message["To"], "recipient@example.com")
        self.assertEqual(message["From"], "sender@gmail.com")
        self.assertIn("2026-11-23 15:01:02", message.get_content())
        self.assertIn("1 則", message.get_content())
        self.assertIn("測試話題", message.get_content())
        self.assertIn("https://kaychen46.github.io/taiwan-trend-radar/", message.get_content())

    @patch("notify_update.smtplib.SMTP_SSL")
    def test_sends_over_authenticated_gmail_smtp(self, smtp_ssl):
        payload = {"updated_at": "2026-11-23 15:01:02", "trends": []}

        send_update_email(
            payload,
            sender="sender@gmail.com",
            recipient="recipient@example.com",
            app_password="example-password",
            site_url="https://kaychen46.github.io/taiwan-trend-radar/",
        )

        smtp_ssl.assert_called_once_with("smtp.gmail.com", 465, timeout=30)
        session = smtp_ssl.return_value.__enter__.return_value
        session.login.assert_called_once_with("sender@gmail.com", "example-password")
        self.assertEqual(session.send_message.call_count, 1)


if __name__ == "__main__":
    unittest.main()
