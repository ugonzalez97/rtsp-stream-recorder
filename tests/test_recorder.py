"""
Unit tests for recorder module
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from recorder import FFmpegRecorder, RECORDINGS_DIR
from models import RecordingConfig


@pytest.fixture
def sample_config():
    """Sample recording configuration"""
    return RecordingConfig(
        camera_id="camera1",
        resolution="1280x720",
        fps="15",
        duration=10,
        duration_unit="seconds",
        codec="libx264",
        quality="23",
        format="mp4",
        extra_args="",
        continuous=False,
        segment_duration=60
    )


@pytest.fixture
def continuous_config():
    """Sample continuous recording configuration"""
    return RecordingConfig(
        camera_id="camera1",
        resolution="1280x720",
        fps="15",
        duration=5,
        duration_unit="minutes",
        codec="copy",
        quality="auto",
        format="ts",
        extra_args="",
        continuous=True,
        segment_duration=300
    )


@pytest.mark.unit
def test_recorder_initialization(sample_config):
    """Test FFmpegRecorder initialization"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    assert recorder.recording_id == "test-id"
    assert recorder.camera_id == "camera1"
    assert recorder.camera_name == "Test Camera"
    assert recorder.rtsp_url == "rtsp://test:test@192.168.1.100:554/stream"
    assert recorder.is_recording is False
    assert recorder.process is None
    assert recorder.filename is None


@pytest.mark.unit
def test_recorder_start_normal_mode(sample_config):
    """Test starting a normal (non-continuous) recording"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    with patch('subprocess.Popen') as mock_popen:
        mock_process = Mock()
        mock_popen.return_value = mock_process
        
        result = recorder.start()
        
        assert result is True
        assert recorder.is_recording is True
        assert recorder.process == mock_process
        assert recorder.filename is not None
        assert mock_popen.called


@pytest.mark.unit
def test_recorder_start_continuous_mode(continuous_config):
    """Test starting a continuous recording with segmentation"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=continuous_config
    )
    
    with patch('subprocess.Popen') as mock_popen:
        mock_process = Mock()
        mock_popen.return_value = mock_process
        
        result = recorder.start()
        
        assert result is True
        assert recorder.is_recording is True
        
        # Check that segmentation arguments were included
        call_args = mock_popen.call_args[0][0]
        assert '-f' in call_args
        assert 'segment' in call_args
        assert '-segment_time' in call_args


@pytest.mark.unit
def test_recorder_start_already_recording(sample_config):
    """Test that starting an already running recorder returns False"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    recorder.is_recording = True
    result = recorder.start()
    
    assert result is False


@pytest.mark.unit
def test_recorder_stop_success(sample_config):
    """Test stopping a recording successfully"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    mock_process = Mock()
    mock_process.wait = Mock(return_value=None)
    recorder.process = mock_process
    recorder.is_recording = True
    recorder.filename = "test.mp4"
    
    result = recorder.stop()
    
    assert result is True
    assert recorder.is_recording is False
    assert mock_process.terminate.called
    assert mock_process.wait.called


@pytest.mark.unit
def test_recorder_stop_force_kill_on_timeout(sample_config):
    """Test that recorder force kills process if terminate times out"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    mock_process = Mock()
    mock_process.wait = Mock(side_effect=[subprocess.TimeoutExpired('cmd', 5), None])
    recorder.process = mock_process
    recorder.is_recording = True
    recorder.filename = "test.mp4"
    
    result = recorder.stop()
    
    assert result is True
    assert mock_process.terminate.called
    assert mock_process.kill.called


@pytest.mark.unit
def test_recorder_stop_not_recording(sample_config):
    """Test stopping when not recording returns False"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    result = recorder.stop()
    assert result is False


@pytest.mark.unit
def test_is_still_recording_active(sample_config):
    """Test is_still_recording when process is active"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    mock_process = Mock()
    mock_process.poll = Mock(return_value=None)  # None means still running
    recorder.process = mock_process
    recorder.is_recording = True
    
    assert recorder.is_still_recording() is True


@pytest.mark.unit
def test_is_still_recording_finished(sample_config):
    """Test is_still_recording when process has finished"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    mock_process = Mock()
    mock_process.poll = Mock(return_value=0)  # 0 means process finished
    recorder.process = mock_process
    recorder.is_recording = True
    recorder.filename = "test.mp4"
    
    assert recorder.is_still_recording() is False
    assert recorder.is_recording is False


@pytest.mark.unit
def test_is_still_recording_no_process(sample_config):
    """Test is_still_recording when no process exists"""
    recorder = FFmpegRecorder(
        recording_id="test-id",
        camera_id="camera1",
        camera_name="Test Camera",
        rtsp_url="rtsp://test:test@192.168.1.100:554/stream",
        config=sample_config
    )
    
    assert recorder.is_still_recording() is False
