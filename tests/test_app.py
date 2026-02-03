"""
Integration tests for FastAPI application
"""
import pytest
from pathlib import Path
from httpx import AsyncClient
from unittest.mock import patch, Mock, AsyncMock
import sys
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from app import app, CAMERAS, active_cameras, active_recordings


@pytest.fixture
def sample_cameras():
    """Sample camera configuration"""
    return {
        "camera1": {
            "name": "Test Camera 1",
            "url": "rtsp://test:test@192.168.1.100:554/stream",
            "enabled": True,
            "info": {
                "max_resolution": {"width": 1920, "height": 1080},
                "max_fps": 30,
                "codecs": ["H264"]
            }
        }
    }


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_endpoint_redirects_to_setup_when_no_cameras():
    """Test that root redirects to setup when no cameras configured"""
    with patch('app.CAMERAS', {}):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/")
            assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_root_endpoint_shows_index_with_cameras(sample_cameras):
    """Test that root shows index when cameras are configured"""
    with patch('app.CAMERAS', sample_cameras):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/")
            assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_setup_page():
    """Test setup page loads"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/setup")
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recording_page():
    """Test recording page loads"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/recording")
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_recordings_viewer_page():
    """Test recordings viewer page loads"""
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.get("/recordings_viewer")
        assert response.status_code == 200


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_cameras_empty():
    """Test listing cameras when none configured"""
    with patch('app.active_cameras', {}):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/cameras")
            assert response.status_code == 200
            data = response.json()
            assert data == {}


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_cameras_with_cameras(sample_cameras):
    """Test listing cameras returns configured cameras"""
    mock_camera = Mock()
    mock_camera.name = "Test Camera 1"
    mock_camera.is_running = True
    mock_camera.rtsp_url = "rtsp://test:test@192.168.1.100:554/stream"
    
    with patch('app.CAMERAS', sample_cameras):
        with patch('app.active_cameras', {"camera1": mock_camera}):
            async with AsyncClient(app=app, base_url="http://test") as client:
                response = await client.get("/api/cameras")
                assert response.status_code == 200
                data = response.json()
                assert "camera1" in data
                assert data["camera1"]["name"] == "Test Camera 1"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_manual_camera_success():
    """Test adding a camera manually by URL"""
    camera_data = {
        "name": "Manual Camera",
        "url": "rtsp://admin:admin@192.168.1.100:554/stream"
    }
    
    with patch('app.CAMERAS', {}):
        with patch('app.active_cameras', {}):
            with patch('app.save_cameras_config') as mock_save:
                with patch('app.FFmpegCamera') as mock_camera_class:
                    mock_camera = Mock()
                    mock_camera.start = AsyncMock()
                    mock_camera_class.return_value = mock_camera
                    
                    async with AsyncClient(app=app, base_url="http://test") as client:
                        response = await client.post("/api/cameras/add-manual", json=camera_data)
                        
                        assert response.status_code == 200
                        data = response.json()
                        assert data["success"] is True
                        assert "camera_id" in data
                        assert mock_save.called


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_manual_camera_missing_fields():
    """Test adding camera with missing fields returns error"""
    camera_data = {"name": "Test"}  # Missing URL
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/api/cameras/add-manual", json=camera_data)
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_add_manual_camera_invalid_url():
    """Test adding camera with invalid URL returns error"""
    camera_data = {
        "name": "Test",
        "url": "http://invalid.com"  # Not rtsp://
    }
    
    async with AsyncClient(app=app, base_url="http://test") as client:
        response = await client.post("/api/cameras/add-manual", json=camera_data)
        assert response.status_code == 400
        data = response.json()
        assert data["success"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_camera_success(sample_cameras):
    """Test deleting a camera successfully"""
    mock_camera = Mock()
    mock_camera.close = AsyncMock()
    
    with patch('app.CAMERAS', sample_cameras.copy()):
        with patch('app.active_cameras', {"camera1": mock_camera}):
            with patch('app.save_cameras_config') as mock_save:
                async with AsyncClient(app=app, base_url="http://test") as client:
                    response = await client.delete("/api/cameras/camera1")
                    
                    assert response.status_code == 200
                    data = response.json()
                    assert data["success"] is True
                    assert mock_camera.close.called
                    assert mock_save.called


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_camera_not_found():
    """Test deleting non-existent camera returns 404"""
    with patch('app.CAMERAS', {}):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.delete("/api/cameras/nonexistent")
            assert response.status_code == 404
            data = response.json()
            assert data["success"] is False


@pytest.mark.asyncio
@pytest.mark.integration
async def test_list_recordings_empty(tmp_path):
    """Test listing recordings when directory is empty"""
    with patch('app.RECORDINGS_DIR', tmp_path):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/recordings/list")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["recordings"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_recordings_success(tmp_path):
    """Test deleting recordings successfully"""
    # Create test files
    test_file1 = tmp_path / "test1.mp4"
    test_file2 = tmp_path / "test2.mp4"
    test_file1.write_text("dummy")
    test_file2.write_text("dummy")
    
    with patch('app.RECORDINGS_DIR', tmp_path):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/recordings/delete",
                json={"filenames": ["test1.mp4", "test2.mp4"]}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["deleted"] == 2
            assert not test_file1.exists()
            assert not test_file2.exists()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_delete_recordings_missing_files(tmp_path):
    """Test deleting recordings includes errors for missing files"""
    with patch('app.RECORDINGS_DIR', tmp_path):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/recordings/delete",
                json={"filenames": ["nonexistent.mp4"]}
            )
            
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert data["deleted"] == 0
            assert len(data["errors"]) == 1


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_active_recordings_empty():
    """Test getting active recordings when none are running"""
    with patch('app.active_recordings', {}):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.get("/api/recordings/active")
            assert response.status_code == 200
            data = response.json()
            assert data["recordings"] == []


@pytest.mark.asyncio
@pytest.mark.integration
async def test_scan_network():
    """Test network scanning endpoint"""
    with patch('app.scan_network_for_rtsp', return_value=[]):
        async with AsyncClient(app=app, base_url="http://test") as client:
            response = await client.post(
                "/api/scan",
                json={"network": "192.168.1.0/24"}
            )
            assert response.status_code == 200
            data = response.json()
            assert "cameras" in data
