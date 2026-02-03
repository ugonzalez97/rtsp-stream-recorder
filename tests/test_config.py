"""
Unit tests for configuration management
"""
import pytest
import json
from pathlib import Path
from unittest.mock import patch, mock_open
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import load_cameras_config, save_cameras_config, CAMERAS_CONFIG_FILE


@pytest.fixture
def sample_config():
    """Sample camera configuration"""
    return {
        "camera1": {
            "name": "Test Camera 1",
            "url": "rtsp://user:pass@192.168.1.100:554/stream",
            "enabled": True,
            "info": {
                "max_resolution": {"width": 1920, "height": 1080},
                "max_fps": 30,
                "codecs": ["H264"]
            }
        },
        "camera2": {
            "name": "Test Camera 2",
            "url": "rtsp://admin:admin@192.168.1.101:554/stream",
            "enabled": False,
            "info": {}
        }
    }


@pytest.mark.unit
def test_load_cameras_config_file_exists(sample_config, tmp_path):
    """Test loading configuration when file exists"""
    config_file = tmp_path / "cameras_config.json"
    config_file.write_text(json.dumps(sample_config))
    
    with patch('config.CAMERAS_CONFIG_FILE', config_file):
        result = load_cameras_config()
        
    assert result == sample_config
    assert len(result) == 2
    assert "camera1" in result
    assert result["camera1"]["name"] == "Test Camera 1"


@pytest.mark.unit
def test_load_cameras_config_file_not_exists(tmp_path):
    """Test loading configuration when file doesn't exist"""
    config_file = tmp_path / "nonexistent.json"
    
    with patch('config.CAMERAS_CONFIG_FILE', config_file):
        result = load_cameras_config()
        
    assert result == {}


@pytest.mark.unit
def test_save_cameras_config(sample_config, tmp_path):
    """Test saving camera configuration"""
    config_file = tmp_path / "cameras_config.json"
    
    with patch('config.CAMERAS_CONFIG_FILE', config_file):
        save_cameras_config(sample_config)
    
    # Verify file was created and contains correct data
    assert config_file.exists()
    saved_data = json.loads(config_file.read_text())
    assert saved_data == sample_config


@pytest.mark.unit
def test_save_cameras_config_empty(tmp_path):
    """Test saving empty configuration"""
    config_file = tmp_path / "cameras_config.json"
    
    with patch('config.CAMERAS_CONFIG_FILE', config_file):
        save_cameras_config({})
    
    assert config_file.exists()
    saved_data = json.loads(config_file.read_text())
    assert saved_data == {}


@pytest.mark.unit
def test_save_cameras_config_overwrites_existing(sample_config, tmp_path):
    """Test that saving overwrites existing configuration"""
    config_file = tmp_path / "cameras_config.json"
    config_file.write_text('{"old": "data"}')
    
    with patch('config.CAMERAS_CONFIG_FILE', config_file):
        save_cameras_config(sample_config)
    
    saved_data = json.loads(config_file.read_text())
    assert "old" not in saved_data
    assert saved_data == sample_config
