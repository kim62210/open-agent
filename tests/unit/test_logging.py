"""Unit tests for core/logging.py — structlog configuration."""

import logging
import os
from unittest.mock import patch

from core.logging import _is_dev_mode, get_logger, setup_logging


class TestIsDevMode:
    def test_dev_mode_via_open_agent_dev(self):
        with patch.dict(os.environ, {"OPEN_AGENT_DEV": "1", "OPEN_AGENT_ENV": "prod"}):
            assert _is_dev_mode() is True

    def test_dev_mode_via_open_agent_env(self):
        with patch.dict(os.environ, {"OPEN_AGENT_DEV": "", "OPEN_AGENT_ENV": "dev"}):
            assert _is_dev_mode() is True

    def test_prod_mode(self):
        with patch.dict(os.environ, {"OPEN_AGENT_DEV": "", "OPEN_AGENT_ENV": "prod"}, clear=False):
            assert _is_dev_mode() is False

    def test_default_is_prod(self):
        env = os.environ.copy()
        env.pop("OPEN_AGENT_DEV", None)
        env.pop("OPEN_AGENT_ENV", None)
        with patch.dict(os.environ, env, clear=True):
            assert _is_dev_mode() is False


class TestSetupLogging:
    def test_setup_sets_root_level(self):
        setup_logging(level="WARNING")
        root = logging.getLogger()
        assert root.level == logging.WARNING

    def test_setup_default_level(self):
        with patch.dict(os.environ, {"OPEN_AGENT_LOG_LEVEL": "DEBUG"}):
            setup_logging()
        root = logging.getLogger()
        assert root.level == logging.DEBUG

    def test_setup_info_level(self):
        with patch.dict(os.environ, {"OPEN_AGENT_LOG_LEVEL": "INFO"}):
            setup_logging()
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_setup_adds_handler(self):
        setup_logging(level="INFO")
        root = logging.getLogger()
        assert len(root.handlers) >= 1

    def test_noisy_loggers_suppressed(self):
        setup_logging(level="DEBUG")
        for name in ("uvicorn.access", "httpx", "httpcore", "litellm"):
            logger = logging.getLogger(name)
            assert logger.level >= logging.WARNING

    def test_uvicorn_loggers_configured(self):
        setup_logging(level="INFO")
        for name in ("uvicorn", "uvicorn.error"):
            logger = logging.getLogger(name)
            assert logger.propagate is False
            assert len(logger.handlers) >= 1

    def test_dev_mode_setup(self):
        with patch.dict(os.environ, {"OPEN_AGENT_DEV": "1"}):
            setup_logging(level="INFO")
        root = logging.getLogger()
        assert root.level == logging.INFO

    def test_prod_mode_setup(self):
        with patch.dict(os.environ, {"OPEN_AGENT_DEV": "", "OPEN_AGENT_ENV": "prod"}):
            setup_logging(level="INFO")
        root = logging.getLogger()
        assert root.level == logging.INFO


class TestGetLogger:
    def test_returns_bound_logger(self):
        logger = get_logger("test_module")
        assert logger is not None
        # structlog BoundLogger should have standard logging methods
        assert hasattr(logger, "info")
        assert hasattr(logger, "warning")
        assert hasattr(logger, "error")
        assert hasattr(logger, "debug")
