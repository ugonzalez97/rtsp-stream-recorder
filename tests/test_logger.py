"""
Unit tests for logger module
"""
import pytest
import logging
from pathlib import Path
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from logger import setup_logger, LOGS_DIR


@pytest.mark.unit
def test_logs_directory_created():
    """Test that logs directory is created"""
    from logger import LOGS_DIR
    
    # After importing logger module, LOGS_DIR should exist
    assert LOGS_DIR.exists()
    assert LOGS_DIR.is_dir()


@pytest.mark.unit
def test_setup_logger_returns_logger():
    """Test that setup_logger returns a logger instance"""
    logger = setup_logger('test_logger')
    assert isinstance(logger, logging.Logger)
    assert logger.name == 'test_logger'


@pytest.mark.unit
def test_setup_logger_default_level():
    """Test that default logging level is INFO"""
    logger = setup_logger('test_default_level')
    assert logger.level == logging.INFO


@pytest.mark.unit
def test_setup_logger_custom_level():
    """Test setting custom logging level"""
    logger = setup_logger('test_custom_level', level=logging.DEBUG)
    assert logger.level == logging.DEBUG


@pytest.mark.unit
def test_setup_logger_has_handlers():
    """Test that logger has console and file handlers"""
    logger = setup_logger('test_handlers')
    
    # Should have at least 2 handlers (console and file)
    assert len(logger.handlers) >= 2
    
    handler_types = [type(h).__name__ for h in logger.handlers]
    assert 'StreamHandler' in handler_types
    assert 'RotatingFileHandler' in handler_types


@pytest.mark.unit
def test_setup_logger_no_duplicate_handlers():
    """Test that calling setup_logger twice doesn't add duplicate handlers"""
    logger1 = setup_logger('test_no_duplicates')
    handler_count1 = len(logger1.handlers)
    
    logger2 = setup_logger('test_no_duplicates')
    handler_count2 = len(logger2.handlers)
    
    assert handler_count1 == handler_count2
    assert logger1 is logger2


@pytest.mark.unit
def test_logger_formats_correctly(caplog):
    """Test that logger formats messages correctly"""
    logger = setup_logger('test_format', level=logging.INFO)
    
    with caplog.at_level(logging.INFO):
        logger.info("Test message")
    
    assert "Test message" in caplog.text
    assert "test_format" in caplog.text
