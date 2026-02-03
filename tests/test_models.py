"""
Unit tests for Pydantic models
"""
import pytest
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from models import CameraSetup, ScanRequest, DetectStreamsRequest, RecordingConfig


@pytest.mark.unit
def test_camera_setup_valid():
    """Test CameraSetup with valid data"""
    camera = CameraSetup(
        ip="192.168.1.100",
        name="Test Camera",
        user="admin",
        password="admin123",
        stream_url="rtsp://admin:admin123@192.168.1.100:554/stream"
    )
    
    assert camera.ip == "192.168.1.100"
    assert camera.name == "Test Camera"
    assert camera.user == "admin"
    assert camera.password == "admin123"
    assert camera.stream_url == "rtsp://admin:admin123@192.168.1.100:554/stream"


@pytest.mark.unit
def test_camera_setup_optional_stream_url():
    """Test CameraSetup with optional stream_url"""
    camera = CameraSetup(
        ip="192.168.1.100",
        name="Test Camera",
        user="admin",
        password="admin123"
    )
    
    assert camera.stream_url is None


@pytest.mark.unit
def test_scan_request_default_network():
    """Test ScanRequest with default network"""
    request = ScanRequest()
    assert request.network == "192.168.1.0/24"


@pytest.mark.unit
def test_scan_request_custom_network():
    """Test ScanRequest with custom network"""
    request = ScanRequest(network="10.0.0.0/24")
    assert request.network == "10.0.0.0/24"


@pytest.mark.unit
def test_detect_streams_request():
    """Test DetectStreamsRequest"""
    request = DetectStreamsRequest(
        ip="192.168.1.100",
        user="admin",
        password="admin123"
    )
    
    assert request.ip == "192.168.1.100"
    assert request.user == "admin"
    assert request.password == "admin123"


@pytest.mark.unit
def test_recording_config_defaults():
    """Test RecordingConfig with default values"""
    config = RecordingConfig(camera_id="camera1")
    
    assert config.camera_id == "camera1"
    assert config.resolution == "original"
    assert config.fps == "original"
    assert config.duration == 10
    assert config.duration_unit == "minutes"
    assert config.codec == "copy"
    assert config.quality == "auto"
    assert config.format == "mp4"
    assert config.extra_args == ""
    assert config.continuous is False
    assert config.segment_duration == 60


@pytest.mark.unit
def test_recording_config_custom_values():
    """Test RecordingConfig with custom values"""
    config = RecordingConfig(
        camera_id="camera1",
        resolution="1920x1080",
        fps="30",
        duration=5,
        duration_unit="hours",
        codec="libx264",
        quality="23",
        format="mkv",
        extra_args="-preset fast",
        continuous=True,
        segment_duration=300
    )
    
    assert config.camera_id == "camera1"
    assert config.resolution == "1920x1080"
    assert config.fps == "30"
    assert config.duration == 5
    assert config.duration_unit == "hours"
    assert config.codec == "libx264"
    assert config.quality == "23"
    assert config.format == "mkv"
    assert config.extra_args == "-preset fast"
    assert config.continuous is True
    assert config.segment_duration == 300


@pytest.mark.unit
def test_recording_config_validation():
    """Test RecordingConfig validation"""
    with pytest.raises(Exception):  # Pydantic ValidationError
        RecordingConfig()  # Missing required camera_id
