"""
Unit tests for camera module
"""
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from camera import FFmpegCamera


@pytest.mark.unit
def test_camera_initialization():
    """Test FFmpegCamera initialization"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    assert camera.camera_id == "camera1"
    assert camera.rtsp_url == "rtsp://admin:admin@192.168.1.100:554/stream"
    assert camera.name == "Test Camera"
    assert camera.is_running is False
    assert camera.process is None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_camera_start():
    """Test starting camera stream"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    with patch('subprocess.Popen') as mock_popen:
        mock_process = Mock()
        mock_popen.return_value = mock_process
        
        await camera.start()
        
        assert camera.is_running is True
        assert camera.process == mock_process
        assert mock_popen.called
        
        # Verify FFmpeg command was constructed
        call_args = mock_popen.call_args[0][0]
        assert 'ffmpeg' in call_args
        assert camera.rtsp_url in call_args


@pytest.mark.asyncio
@pytest.mark.unit
async def test_camera_start_already_running():
    """Test that starting an already running camera logs warning"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    camera.is_running = True
    
    with patch('camera.logger') as mock_logger:
        await camera.start()
        mock_logger.warning.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.unit
async def test_camera_close():
    """Test closing camera stream"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    mock_process = Mock()
    mock_process.wait = Mock(return_value=None)
    camera.process = mock_process
    camera.is_running = True
    
    await camera.close()
    
    assert camera.is_running is False
    assert camera.process is None
    assert mock_process.terminate.called
    assert mock_process.wait.called


@pytest.mark.asyncio
@pytest.mark.unit
async def test_camera_close_force_kill_on_timeout():
    """Test that camera force kills process if terminate times out"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    mock_process = Mock()
    mock_process.wait = Mock(side_effect=subprocess.TimeoutExpired('cmd', 3))
    camera.process = mock_process
    camera.is_running = True
    
    await camera.close()
    
    assert camera.is_running is False
    assert mock_process.terminate.called
    assert mock_process.kill.called


@pytest.mark.unit
def test_camera_read_frame_no_frame():
    """Test read_frame returns None when no frame available"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    frame = camera.read_frame()
    assert frame is None


@pytest.mark.unit
def test_camera_read_frame_timeout():
    """Test read_frame returns None when queue is empty"""
    camera = FFmpegCamera(
        camera_id="camera1",
        rtsp_url="rtsp://admin:admin@192.168.1.100:554/stream",
        name="Test Camera"
    )
    
    # With empty queue, should return None
    frame = camera.read_frame()
    assert frame is None
