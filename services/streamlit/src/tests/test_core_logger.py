"""
Tests for core/logger.py - Centralized logging configuration.
"""

import logging
import pytest

from src.core.logger import get_logger, logger


class TestGetLogger:
    """Tests for get_logger function."""

    def test_returns_logger_instance(self):
        result = get_logger("test_module")
        assert isinstance(result, logging.Logger)

    def test_default_name(self):
        result = get_logger()
        assert result.name == "metaplanet"

    def test_custom_name(self):
        result = get_logger("custom.module")
        assert result.name == "custom.module"

    def test_same_name_returns_same_logger(self):
        logger1 = get_logger("same_name")
        logger2 = get_logger("same_name")
        assert logger1 is logger2

    def test_different_names_return_different_loggers(self):
        logger1 = get_logger("name1")
        logger2 = get_logger("name2")
        assert logger1 is not logger2


class TestModuleLogger:
    """Tests for module-level logger instance."""

    def test_module_logger_exists(self):
        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_module_logger_name(self):
        assert logger.name == "metaplanet"

    def test_module_logger_level(self):
        assert logger.level == logging.INFO

    def test_module_logger_has_handler(self):
        # The module should have at least one handler
        assert len(logger.handlers) > 0

    def test_can_log_without_error(self):
        # Should not raise any errors
        logger.debug("Test debug message")
        logger.info("Test info message")
        logger.warning("Test warning message")
        logger.error("Test error message")
