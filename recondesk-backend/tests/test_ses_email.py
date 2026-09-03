"""Unit tests for Amazon SES SMTP email sending and sendEmail utility."""

import email
from unittest.mock import MagicMock, patch

import pytest

from app.config import get_settings
from app.utils.email import (
    send_email,
    sendEmail,
    send_welcome_email,
)


@pytest.fixture
def mock_settings(monkeypatch):
    """Set standard SES environment settings for testing."""
    monkeypatch.setenv("SES_SMTP_HOST", "email-smtp.ap-south-1.amazonaws.com")
    monkeypatch.setenv("SES_SMTP_PORT", "587")
    monkeypatch.setenv("SES_SMTP_USER", "AKIA_TEST_USER")
    monkeypatch.setenv("SES_SMTP_PASS", "TEST_PASSWORD_SECRET")
    monkeypatch.setenv("EMAIL_FROM", "ReconDesk <noreply@recondesk.in>")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_send_email_smtp_success(mock_settings):
    """Test successful email sending via SES SMTP."""
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        success = sendEmail(
            to="recipient@example.com",
            subject="Test Subject",
            body="<h1>Hello World</h1>",
            text_body="Hello World",
        )

        assert success is True
        mock_smtp_cls.assert_called_once_with(
            "email-smtp.ap-south-1.amazonaws.com", 587, timeout=30
        )
        assert mock_server.starttls.called
        mock_server.login.assert_called_once_with("AKIA_TEST_USER", "TEST_PASSWORD_SECRET")
        assert mock_server.sendmail.called

        # Inspect sent message
        args, kwargs = mock_server.sendmail.call_args
        from_addr, to_addrs, raw_msg = args
        assert from_addr == "ReconDesk <noreply@recondesk.in>"
        assert to_addrs == ["recipient@example.com"]
        
        parsed_msg = email.message_from_string(raw_msg)
        assert parsed_msg["Subject"] == "Test Subject"
        payload_text = ""
        for part in parsed_msg.walk():
            payload = part.get_payload(decode=True)
            if payload:
                payload_text += payload.decode("utf-8")
        assert "<h1>Hello World</h1>" in payload_text
        assert "Hello World" in payload_text


def test_send_email_smtp_with_attachment(mock_settings, tmp_path):
    """Test email sending with a valid file attachment."""
    # Create a temporary attachment
    test_file = tmp_path / "invoice.pdf"
    test_file.write_bytes(b"%PDF-1.4 test invoice content")

    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        success = sendEmail(
            to=["recipient1@example.com", "recipient2@example.com"],
            subject="Invoice Attached",
            body="<p>Please find your invoice attached.</p>",
            attachment=str(test_file),
        )

        assert success is True
        assert mock_server.sendmail.called
        args, kwargs = mock_server.sendmail.call_args
        from_addr, to_addrs, raw_msg = args
        assert to_addrs == ["recipient1@example.com", "recipient2@example.com"]
        assert "filename=\"invoice.pdf\"" in raw_msg
        assert "Content-Disposition: attachment" in raw_msg


def test_send_email_smtp_missing_attachment(mock_settings):
    """Test email sending fails safely when attachment path does not exist."""
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        success = sendEmail(
            to="recipient@example.com",
            subject="Missing File",
            body="<p>Hello</p>",
            attachment="/nonexistent/path/to/missing_file.pdf",
        )

        assert success is False
        assert not mock_server.sendmail.called


def test_send_email_smtp_missing_credentials(monkeypatch):
    """Test that missing SES credentials returns False without raising."""
    monkeypatch.setenv("SES_SMTP_USER", "")
    monkeypatch.setenv("SES_SMTP_PASS", "")
    get_settings.cache_clear()

    with patch("smtplib.SMTP") as mock_smtp_cls:
        success = sendEmail(
            to="recipient@example.com",
            subject="No Credentials",
            body="<p>Test</p>",
        )
        assert success is False
        assert not mock_smtp_cls.called

    get_settings.cache_clear()


def test_send_email_smtp_connection_failure(mock_settings):
    """Test handling of SMTP connection error gracefully."""
    with patch("smtplib.SMTP", side_effect=Exception("Connection refused")):
        success = sendEmail(
            to="recipient@example.com",
            subject="Fail Subject",
            body="<p>Fail</p>",
        )
        assert success is False


@pytest.mark.asyncio
async def test_async_send_email_wrapper(mock_settings):
    """Test async send_email helper function."""
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        success = await send_email(
            to="async_recipient@example.com",
            subject="Async Subject",
            html_content="<p>Async body</p>",
        )

        assert success is True
        assert mock_server.sendmail.called


@pytest.mark.asyncio
async def test_async_send_welcome_email(mock_settings):
    """Test sending branded welcome email via SES."""
    with patch("smtplib.SMTP") as mock_smtp_cls:
        mock_server = MagicMock()
        mock_smtp_cls.return_value.__enter__.return_value = mock_server

        success = await send_welcome_email(
            to="ca.sharma@example.com",
            full_name="CA Sharma",
        )

        assert success is True
        assert mock_server.sendmail.called
        args, kwargs = mock_server.sendmail.call_args
        from_addr, to_addrs, raw_msg = args
        parsed_msg = email.message_from_string(raw_msg)
        payload_text = ""
        for part in parsed_msg.walk():
            payload = part.get_payload(decode=True)
            if payload:
                payload_text += payload.decode("utf-8")
        assert "Welcome to ReconDesk" in payload_text
        assert "CA Sharma" in payload_text
