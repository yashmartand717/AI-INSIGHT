from django.test import SimpleTestCase
from django.core.exceptions import ImproperlyConfigured
from gyanbuddy_insights.gmail import gmail_smtp_settings


class GmailSettingsTests(SimpleTestCase):
    def test_missing_sender_or_secret_is_rejected(self):
        for config in ({}, {'GMAIL_SENDER_EMAIL': 'not-an-email', 'GMAIL_APP_PASSWORD': 'test'}, {'GMAIL_SENDER_EMAIL': 'school@example.test'}):
            with self.subTest(config=config), self.assertRaises(ImproperlyConfigured):
                gmail_smtp_settings(config)
