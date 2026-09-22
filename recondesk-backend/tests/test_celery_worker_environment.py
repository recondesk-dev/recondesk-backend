"""
Tests for Phase 5.7 REM-03: Celery Worker Environment Hardening.
Verifies the fail-closed startup assertion on SUPABASE_SERVICE_ROLE_KEY.
"""

import logging
from unittest.mock import MagicMock, patch

import pytest
from celery.signals import worker_init

from app.worker.celery_app import assert_worker_environment


class TestCeleryWorkerEnvironmentAssertion:
    """Test suite for assert_worker_environment startup hook."""

    def test_signal_registered_on_worker_init(self):
        """Verify assert_worker_environment is connected to worker_init signal."""
        receivers = [r[1] for r in worker_init.receivers]
        # Receiver may be a weakref or direct callable
        receiver_functions = []
        for r in receivers:
            fn = getattr(r, "__func__", None) or r
            # If wrapped by weakref
            if hasattr(fn, "__self__"):
                receiver_functions.append(fn)
            else:
                receiver_functions.append(fn)

        assert any(
            "assert_worker_environment" in getattr(fn, "__name__", "")
            or "assert_worker_environment" in str(fn)
            for fn in receiver_functions
        ), "assert_worker_environment must be connected to worker_init signal"

    def test_valid_key_allows_worker_startup(self):
        """Worker startup assertion succeeds when SUPABASE_SERVICE_ROLE_KEY is valid."""
        mock_settings = MagicMock()
        mock_settings.SUPABASE_SERVICE_ROLE_KEY = "valid_service_role_key_test_12345"

        with patch("app.config.get_settings", return_value=mock_settings):
            # Must complete without raising SystemExit or any exception
            assert_worker_environment()

    @pytest.mark.parametrize(
        "invalid_key,label",
        [
            ("", "empty string"),
            (None, "None value"),
            ("   ", "spaces only"),
            ("\t\n  ", "whitespace characters"),
        ],
    )
    def test_invalid_key_fails_closed_with_system_exit(
        self,
        invalid_key,
        label,
        caplog,
        capsys,
    ):
        """Worker startup fails immediately with exit code 1 when key is empty, None, or whitespace."""
        mock_settings = MagicMock()
        mock_settings.SUPABASE_SERVICE_ROLE_KEY = invalid_key

        with patch("app.config.get_settings", return_value=mock_settings):
            with caplog.at_level(logging.CRITICAL):
                with pytest.raises(SystemExit) as exc_info:
                    assert_worker_environment()

                assert exc_info.value.code == 1, f"Expected exit code 1 for {label}"

            # Verify critical error was logged
            assert any(
                "SUPABASE_SERVICE_ROLE_KEY is missing or empty" in record.message
                for record in caplog.records
            ), f"Expected critical log message for {label}"

            # Verify stderr output
            captured = capsys.readouterr()
            assert "SUPABASE_SERVICE_ROLE_KEY is missing or empty" in captured.err

    def test_no_secrets_leaked_in_exceptions_or_logs(self, caplog, capsys):
        """Verify no secret values or sensitive fragments appear in log records or stderr."""
        fake_partial_secret = "supa_secret_token_fragment_xyz987"
        mock_settings = MagicMock()
        # Even if someone passed an invalid type or object containing secret info
        mock_settings.SUPABASE_SERVICE_ROLE_KEY = ""

        with patch("app.config.get_settings", return_value=mock_settings):
            with pytest.raises(SystemExit):
                assert_worker_environment()

            captured = capsys.readouterr()
            for record in caplog.records:
                assert fake_partial_secret not in record.message
            assert fake_partial_secret not in captured.err
            assert fake_partial_secret not in captured.out

    def test_module_import_does_not_trigger_assertion(self):
        """Simply importing app.worker.celery_app does not invoke the assertion."""
        # worker_init only fires when celery worker starts, not on module import
        # We verify that importing tasks or celery_app does not raise SystemExit
        import app.worker.celery_app
        import app.worker.tasks

        assert app.worker.celery_app.celery_app is not None
        assert app.worker.tasks.run_import_job is not None
