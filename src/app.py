"""
Main FastAPI application for RTSP camera viewing and recording
"""
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
import asyncio
from typing import Dict
import subprocess
from pathlib import Path
import uuid
import re
import mimetypes

# Import own modules
from models import CameraSetup, ScanRequest, DetectStreamsRequest, RecordingConfig
from camera import FFmpegCamera
from recorder import FFmpegRecorder, RECORDINGS_DIR
from config import load_cameras_config, save_cameras_config
from network_utils import (
    scan_network_for_rtsp,
    get_rtsp_urls_from_onvif,
    get_camera_info_from_onvif
)
from logger import setup_logger

# Setup logger
logger = setup_logger(__name__)


app = FastAPI(title="RTSP Stream Recorder")
templates = Jinja2Templates(directory="templates")

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

# Application global state
CAMERAS = {}
active_cameras: Dict[str, FFmpegCamera] = {}
active_recordings: Dict[str, FFmpegRecorder] = {}


def generate_frames(camera_id: str):
    """Frame generator for MJPEG streaming using FFmpeg"""
    camera = active_cameras.get(camera_id)
    
    if not camera:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    
    while camera.is_running:
        frame = camera.read_frame()
        
        if frame is not None:
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')


@app.on_event("startup")
async def startup_event():
    """Initializes cameras on application startup"""
    global CAMERAS
    CAMERAS = load_cameras_config()
    
    if not CAMERAS:
        logger.warning("No cameras configured. Access /setup to configure cameras")
        return
    
    logger.info(f"Loading {len(CAMERAS)} configured camera(s)")
    
    for camera_id, config in CAMERAS.items():
        if config.get("enabled", True):
            camera = FFmpegCamera(
                camera_id=camera_id,
                rtsp_url=config["url"],
                name=config["name"]
            )
            active_cameras[camera_id] = camera
            
            try:
                await camera.start()
                logger.info(f"Camera started successfully: {config['name']} ({camera_id})")
            except Exception as e:
                logger.error(f"Failed to start camera {config['name']}: {e}")
    
    # Start background task to clean up finished recordings
    asyncio.create_task(cleanup_finished_recordings())


@app.on_event("shutdown")
async def shutdown_event():
    """Free resources on application close"""
    for camera in active_cameras.values():
        await camera.close()


async def cleanup_finished_recordings():
    """Background task that periodically checks and removes finished recordings"""
    logger.info("Started background task: cleanup_finished_recordings")
    
    while True:
        try:
            await asyncio.sleep(5)  # Check every 5 seconds
            
            finished = []
            for recording_id, recorder in list(active_recordings.items()):
                if not recorder.is_still_recording():
                    finished.append(recording_id)
            
            # Remove finished recordings
            for recording_id in finished:
                recorder = active_recordings[recording_id]
                logger.info(f"Removing finished recording from active list: {recorder.filename}")
                del active_recordings[recording_id]
                
        except Exception as e:
            logger.error(f"Error in cleanup_finished_recordings task: {e}")
            await asyncio.sleep(10)  # Wait longer if there's an error


# ========== HTML ROUTES ==========

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Main page with camera viewer"""
    if not CAMERAS:
        return templates.TemplateResponse("setup.html", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Camera configuration page"""
    return templates.TemplateResponse("setup.html", {"request": request})


@app.get("/recording", response_class=HTMLResponse)
async def recording_page(request: Request):
    """Camera recording page"""
    return templates.TemplateResponse("recording.html", {"request": request})


@app.get("/recordings_viewer", response_class=HTMLResponse)
async def recordings_viewer_page(request: Request):
    """Recordings viewing page"""
    return templates.TemplateResponse("recordings_viewer.html", {"request": request})


@app.get("/recordings/watch/{filename:path}", response_class=HTMLResponse)
async def watch_recording(request: Request, filename: str):
    """Page to play a specific recording"""
    recording_path = RECORDINGS_DIR / filename
    if recording_path.exists():
        return templates.TemplateResponse("watch.html", {"request": request, "video": filename})
    raise HTTPException(status_code=404, detail="Grabación no encontrada")


# ========== API: CAMERA CONFIGURATION ==========

@app.post("/api/scan")
async def scan_network(scan_req: ScanRequest):
    """Endpoint to scan network for cameras"""
    try:
        cameras = await asyncio.to_thread(scan_network_for_rtsp, scan_req.network)
        return JSONResponse({
            "success": True,
            "cameras": cameras
        })
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


@app.post("/api/detect-streams")
async def detect_streams(req: DetectStreamsRequest):
    """Detects available ONVIF streams from a camera"""
    try:
        logger.info(f"Detecting streams from camera at {req.ip}")
        streams = await asyncio.to_thread(
            get_rtsp_urls_from_onvif,
            req.ip,
            80,
            req.user,
            req.password
        )
        
        logger.info(f"Found {len(streams)} stream(s) from {req.ip}")
        return JSONResponse({
            "success": True,
            "streams": streams
        })
    except Exception as e:
        logger.error(f"Error detecting streams from {req.ip}: {e}")
        return JSONResponse(
            {"success": False, "message": str(e), "streams": []},
            status_code=500
        )


@app.post("/api/cameras/setup")
async def setup_cameras(request: Request):
    """Configures selected cameras"""
    try:
        data = await request.json()
        cameras_data = data.get('cameras', [])
        
        global CAMERAS
        CAMERAS = {}
        
        for idx, cam_data in enumerate(cameras_data):
            camera_id = f"camera{idx + 1}"
            
            # If specific stream already selected, use it
            if cam_data.get('stream_url'):
                rtsp_url = cam_data['stream_url']
                logger.info(f"Using pre-selected stream for {cam_data['name']}: {rtsp_url}")
            else:
                # Try to get RTSP URL using ONVIF
                streams = await asyncio.to_thread(
                    get_rtsp_urls_from_onvif,
                    cam_data['ip'],
                    80,
                    cam_data['user'],
                    cam_data['password']
                )
                
                rtsp_url = streams[0]['url'] if streams else f"rtsp://{cam_data['user']}:{cam_data['password']}@{cam_data['ip']}:554/stream"
            
            # Get camera information
            camera_info = await asyncio.to_thread(
                get_camera_info_from_onvif,
                cam_data['ip'],
                80,
                cam_data['user'],
                cam_data['password']
            )
            
            CAMERAS[camera_id] = {
                "name": cam_data['name'],
                "url": rtsp_url,
                "enabled": True,
                "info": camera_info
            }
        
        # Save configuration
        save_cameras_config(CAMERAS)
        
        # Restart cameras
        for camera in list(active_cameras.values()):
            await camera.close()
        active_cameras.clear()
        
        for camera_id, config in CAMERAS.items():
            camera = FFmpegCamera(
                camera_id=camera_id,
                rtsp_url=config["url"],
                name=config["name"]
            )
            active_cameras[camera_id] = camera
            await camera.start()
        
        return JSONResponse({"success": True, "message": "Cámaras configuradas"})
        
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


@app.get("/api/cameras")
async def list_cameras():
    """Lists all available cameras with their information"""
    cameras_info = {}
    for camera_id, camera in active_cameras.items():
        camera_config = CAMERAS.get(camera_id, {})
        cameras_info[camera_id] = {
            "name": camera.name,
            "running": camera.is_running,
            "url": camera.rtsp_url,
            "info": camera_config.get("info", {
                "max_resolution": {"width": 1920, "height": 1080},
                "max_fps": 30,
                "codecs": ["H264"]
            })
        }
    return cameras_info


@app.post("/api/cameras/add-manual")
async def add_manual_camera(request: Request):
    """Add a camera manually by URL"""
    try:
        data = await request.json()
        name = data.get('name', '').strip()
        url = data.get('url', '').strip()
        
        if not name or not url:
            return JSONResponse(
                {"success": False, "message": "Nombre y URL son requeridos"},
                status_code=400
            )
        
        if not url.startswith('rtsp://'):
            return JSONResponse(
                {"success": False, "message": "URL debe comenzar con rtsp://"},
                status_code=400
            )
        
        global CAMERAS
        
        # Generate new camera ID
        camera_num = len(CAMERAS) + 1
        camera_id = f"camera{camera_num}"
        while camera_id in CAMERAS:
            camera_num += 1
            camera_id = f"camera{camera_num}"
        
        # Add camera to config
        CAMERAS[camera_id] = {
            "name": name,
            "url": url,
            "enabled": True,
            "info": {
                "max_resolution": {"width": 1920, "height": 1080},
                "max_fps": 30,
                "codecs": ["H264"]
            }
        }
        
        # Save configuration
        save_cameras_config(CAMERAS)
        
        # Start camera
        camera = FFmpegCamera(
            camera_id=camera_id,
            rtsp_url=url,
            name=name
        )
        active_cameras[camera_id] = camera
        await camera.start()
        
        logger.info(f"Manual camera added successfully: {name} ({camera_id}) - {url}")
        return JSONResponse({"success": True, "camera_id": camera_id})
        
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


@app.delete("/api/cameras/{camera_id}")
async def delete_camera(camera_id: str):
    """Delete a configured camera"""
    try:
        global CAMERAS
        
        if camera_id not in CAMERAS:
            return JSONResponse(
                {"success": False, "message": "Cámara no encontrada"},
                status_code=404
            )
        
        # Stop camera if running
        if camera_id in active_cameras:
            await active_cameras[camera_id].close()
            del active_cameras[camera_id]
        
        # Remove from config
        del CAMERAS[camera_id]
        save_cameras_config(CAMERAS)
        
        logger.info(f"Camera deleted successfully: {camera_id}")
        return JSONResponse({"success": True})
        
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


# ========== API: VIDEO STREAMING ==========

@app.get("/video_feed/{camera_id}")
async def video_feed(camera_id: str):
    """Endpoint for MJPEG streaming of a specific camera"""
    if camera_id not in active_cameras:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    
    return StreamingResponse(
        generate_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )


# ========== API: RECORDING ==========

@app.post("/api/recording/start")
async def start_recording(config: RecordingConfig):
    """Starts a new recording"""
    try:
        # Verify camera exists
        if config.camera_id not in CAMERAS:
            return JSONResponse(
                {"success": False, "message": "Cámara no encontrada"},
                status_code=404
            )
        
        camera_config = CAMERAS[config.camera_id]
        recording_id = str(uuid.uuid4())
        
        # Create recorder with camera information
        recorder = FFmpegRecorder(
            recording_id=recording_id,
            camera_id=config.camera_id,
            camera_name=camera_config['name'],
            rtsp_url=camera_config['url'],
            config=config,
            camera_info=camera_config.get('info', {})
        )
        
        # Start recording in separate thread
        success = await asyncio.to_thread(recorder.start)
        
        if success:
            active_recordings[recording_id] = recorder
            logger.info(f"Recording started: {camera_config['name']} - {recorder.filename}")
            return JSONResponse({
                "success": True,
                "recording_id": recording_id,
                "filename": recorder.filename
            })
        else:
            logger.error(f"Failed to start recording for camera: {camera_config['name']}")
            return JSONResponse(
                {"success": False, "message": "Error al iniciar grabación"},
                status_code=500
            )
            
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


@app.post("/api/recording/stop/{recording_id}")
async def stop_recording(recording_id: str):
    """Stops an active recording"""
    try:
        if recording_id not in active_recordings:
            return JSONResponse(
                {"success": False, "message": "Grabación no encontrada"},
                status_code=404
            )
        
        recorder = active_recordings[recording_id]
        success = await asyncio.to_thread(recorder.stop)
        
        if success:
            logger.info(f"Recording stopped: {recorder.camera_name} - {recorder.filename}")
            del active_recordings[recording_id]
            return JSONResponse({"success": True})
        else:
            return JSONResponse(
                {"success": False, "message": "Error al detener grabación"},
                status_code=500
            )
            
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


@app.get("/api/recordings/active")
async def get_active_recordings():
    """Lists all active recordings"""
    recordings = []
    for rec_id, recorder in active_recordings.items():
        recordings.append({
            "id": rec_id,
            "camera_id": recorder.camera_id,
            "camera_name": recorder.camera_name,
            "filename": recorder.filename,
            "start_time": recorder.start_time.isoformat() if recorder.start_time else None,
            "is_recording": recorder.is_recording,
            "continuous": recorder.config.continuous,
            "segment_duration": recorder.config.segment_duration if recorder.config.continuous else None,
            "total_duration": recorder.config.duration,
            "duration_unit": recorder.config.duration_unit
        })
    
    return JSONResponse({"recordings": recordings})


# ========== API: RECORDING FILES ==========

@app.get("/api/recordings/list")
async def list_recordings():
    """Lists all saved recordings"""
    try:
        recordings = []
        if RECORDINGS_DIR.exists():
            for file in RECORDINGS_DIR.iterdir():
                if file.is_file():
                    stats = file.stat()
                    
                    # Get video duration using ffprobe
                    duration = None
                    try:
                        result = subprocess.run(
                            ['ffprobe', '-v', 'error', '-show_entries', 
                             'format=duration', '-of', 
                             'default=noprint_wrappers=1:nokey=1', str(file)],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if result.returncode == 0:
                            duration = float(result.stdout.strip())
                    except Exception as e:
                        logger.debug(f"Could not get duration for {file.name}: {e}")
                    
                    recordings.append({
                        'filename': file.name,
                        'size': stats.st_size,
                        'modified': stats.st_mtime,
                        'format': file.suffix[1:] if file.suffix else 'unknown',
                        'duration': duration
                    })
        
        return JSONResponse({
            "success": True,
            "recordings": recordings
        })
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e), "recordings": []},
            status_code=500
        )


@app.post("/api/recordings/delete")
async def delete_recordings(request: Request):
    """Delete selected recordings"""
    try:
        data = await request.json()
        filenames = data.get('filenames', [])
        
        if not filenames:
            return JSONResponse(
                {"success": False, "message": "No se especificaron archivos"},
                status_code=400
            )
        
        deleted = 0
        errors = []
        
        for filename in filenames:
            try:
                file_path = RECORDINGS_DIR / filename
                
                # Security check: ensure file is within recordings directory
                if not file_path.resolve().parent == RECORDINGS_DIR.resolve():
                    errors.append(f"{filename}: ruta inválida")
                    continue
                
                if file_path.exists() and file_path.is_file():
                    file_path.unlink()
                    deleted += 1
                    logger.info(f"Recording deleted: {filename}")
                else:
                    errors.append(f"{filename}: no encontrado")
                    
            except Exception as e:
                errors.append(f"{filename}: {str(e)}")
        
        return JSONResponse({
            "success": True,
            "deleted": deleted,
            "errors": errors
        })
        
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e)},
            status_code=500
        )


@app.get("/recordings/serve/{filename:path}")
async def serve_recording(filename: str, request: Request):
    """Serves recording files with Range Request support for streaming"""
    try:
        file_path = RECORDINGS_DIR / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Grabación no encontrada")
        
        file_size = file_path.stat().st_size
        
        # Get MIME type
        mimetype = mimetypes.guess_type(filename)[0]
        
        # Handle special MIME type cases
        if not mimetype:
            ext = file_path.suffix.lower()
            mime_map = {
                '.mp4': 'video/mp4',
                '.mkv': 'video/x-matroska',
                '.ts': 'video/mp2t',
                '.avi': 'video/x-msvideo',
                '.mov': 'video/quicktime',
                '.webm': 'video/webm'
            }
            mimetype = mime_map.get(ext, 'video/mp4')
        elif file_path.suffix.lower() == '.ts':
            # Force correct type for .ts files
            mimetype = 'video/mp2t'
        
        # Parse Range header
        range_header = request.headers.get('range', None)
        
        if not range_header:
            # No range request, send complete file
            return FileResponse(
                str(file_path),
                media_type=mimetype,
                headers={
                    'Accept-Ranges': 'bytes',
                    'Content-Length': str(file_size)
                }
            )
        
        # Parse requested range
        match = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if not match:
            raise HTTPException(status_code=416, detail="Invalid Range header")
        
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1
        
        # Validate range
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        
        # Calculate content length to send
        content_length = end - start + 1
        
        # Read requested file portion
        def generate():
            with open(file_path, 'rb') as f:
                f.seek(start)
                remaining = content_length
                chunk_size = 8192
                
                while remaining > 0:
                    chunk = f.read(min(chunk_size, remaining))
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        
        # Create 206 Partial Content response
        return StreamingResponse(
            generate(),
            status_code=206,
            media_type=mimetype,
            headers={
                'Content-Range': f'bytes {start}-{end}/{file_size}',
                'Content-Length': str(content_length),
                'Accept-Ranges': 'bytes',
                'Cache-Control': 'no-cache'
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al servir grabación: {str(e)}")


# ========== ENTRY POINT ==========

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
