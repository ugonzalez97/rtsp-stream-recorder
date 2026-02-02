from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse, HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
import asyncio
from typing import Optional, Dict, List
import subprocess
from pathlib import Path
import threading
from queue import Queue, Empty
import time
import json
import nmap
from onvif import ONVIFCamera
from pydantic import BaseModel
from datetime import datetime
import uuid
import os

app = FastAPI(title="RTSP Stream Viewer")
templates = Jinja2Templates(directory="templates")

# Configuración de cámaras (se cargará dinámicamente)
CAMERAS = {}
CAMERAS_CONFIG_FILE = Path("cameras_config.json")

# Modelos Pydantic para validación
class CameraSetup(BaseModel):
    ip: str
    name: str
    user: str
    password: str
    stream_url: Optional[str] = None

class ScanRequest(BaseModel):
    network: str = "192.168.1.0/24"

class DetectStreamsRequest(BaseModel):
    ip: str
    user: str
    password: str

class RecordingConfig(BaseModel):
    camera_id: str
    resolution: str = "original"
    fps: str = "original"
    duration: int = 10
    duration_unit: str = "minutes"  # seconds, minutes, hours
    codec: str = "copy"
    quality: str = "auto"
    format: str = "mp4"
    extra_args: str = ""
    continuous: bool = False  # Grabación continua con segmentos
    segment_duration: int = 15  # Duración de cada segmento en minutos (para modo continuo)

class FFmpegCamera:
    """Maneja el streaming de una cámara RTSP usando FFmpeg con baja latencia"""
    
    def __init__(self, camera_id: str, rtsp_url: str, name: str = "Camera"):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.name = name
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.frame_queue: Queue = Queue(maxsize=2)  # Buffer pequeño: solo 2 frames
        self.reader_thread: Optional[threading.Thread] = None
        
    async def start(self):
        """Inicia el proceso FFmpeg para capturar el stream RTSP"""
        if self.is_running:
            return
            
        try:
            # Comando FFmpeg optimizado para BAJA LATENCIA (solo video para preview rápido)
            command = [
                'ffmpeg',
                # Flags de baja latencia
                '-fflags', 'nobuffer',  # Sin buffering
                '-flags', 'low_delay',  # Modo baja latencia
                '-rtsp_transport', 'tcp',
                '-i', self.rtsp_url,
                # Procesamiento mínimo
                '-f', 'image2pipe',
                '-vcodec', 'mjpeg',
                '-q:v', '8',  # Calidad media para mayor velocidad
                '-vf', 'scale=1280:-1',  # Escalar si es muy grande
                '-r', '15',  # 15 FPS
                # Más flags de optimización
                '-probesize', '32',  # Reducir análisis inicial
                '-analyzeduration', '0',  # No analizar duración
                '-'
            ]
            
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0  # Sin buffer en el pipe
            )
            self.is_running = True
            
            # Iniciar thread de lectura
            self.reader_thread = threading.Thread(target=self._read_frames, daemon=True)
            self.reader_thread.start()
            
            print(f"✅ FFmpeg iniciado para {self.name} ({self.camera_id}) - Modo baja latencia")
            
        except Exception as e:
            print(f"❌ Error iniciando FFmpeg para {self.name}: {e}")
            raise
    
    def _read_frames(self):
        """Thread que lee frames continuamente y mantiene solo el más reciente"""
        while self.is_running:
            try:
                frame = self._read_single_frame()
                if frame:
                    # Si la cola está llena, descartar frame viejo
                    while self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()  # Descartar frame viejo
                        except Empty:
                            break
                    
                    try:
                        self.frame_queue.put_nowait(frame)
                    except:
                        pass  # Si no se puede agregar, seguir
            except Exception as e:
                if self.is_running:
                    print(f"⚠️ Error en thread de lectura {self.name}: {e}")
                    time.sleep(0.1)
    
    def _read_single_frame(self) -> Optional[bytes]:
        """Lee un frame del proceso FFmpeg"""
        if not self.process or not self.is_running:
            return None
            
        try:
            # Buscar el marcador de inicio de JPEG (FFD8)
            while True:
                byte = self.process.stdout.read(1)
                if not byte:
                    return None
                if byte == b'\xff':
                    byte2 = self.process.stdout.read(1)
                    if byte2 == b'\xd8':  # Inicio de JPEG
                        break
            
            # Leer hasta el marcador de fin de JPEG (FFD9)
            jpg = b'\xff\xd8'
            while True:
                byte = self.process.stdout.read(1)
                if not byte:
                    return None
                jpg += byte
                if len(jpg) >= 2 and jpg[-2:] == b'\xff\xd9':  # Fin de JPEG
                    return jpg
                    
        except Exception as e:
            return None
    
    def read_frame(self) -> Optional[bytes]:
        """Obtiene el frame más reciente de la cola (descartando viejos si los hay)"""
        if not self.is_running:
            return None
        
        try:
            # Obtener el frame más reciente, descartando viejos si hay varios
            frame = None
            while True:
                try:
                    frame = self.frame_queue.get(timeout=0.5)
                    # Si hay más frames en cola, obtener el siguiente (más reciente)
                    if not self.frame_queue.empty():
                        continue
                    break
                except Empty:
                    # Si no hay frames, devolver el último que teníamos
                    break
            return frame
        except Exception as e:
            return None
    
    async def close(self):
        """Cierra el proceso FFmpeg"""
        self.is_running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        print(f"🔌 FFmpeg detenido para {self.name}")

# Diccionario global de cámaras activas
active_cameras: Dict[str, FFmpegCamera] = {}

# Directorio y diccionario de grabaciones
RECORDINGS_DIR = Path("recordings")
RECORDINGS_DIR.mkdir(exist_ok=True)
active_recordings: Dict[str, 'FFmpegRecorder'] = {}

class FFmpegRecorder:
    """Maneja la grabación de una cámara RTSP usando FFmpeg"""
    
    def __init__(self, recording_id: str, camera_id: str, camera_name: str, rtsp_url: str, config: RecordingConfig):
        self.recording_id = recording_id
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.config = config
        self.process: Optional[subprocess.Popen] = None
        self.is_recording = False
        self.start_time = None
        self.filename = None
        
    def start(self):
        """Inicia la grabación"""
        if self.is_recording:
            return False
        
        try:
            # Generar nombre de archivo
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Construir comando FFmpeg
            command = [
                'ffmpeg',
                '-rtsp_transport', 'tcp',
                '-i', self.rtsp_url,
            ]
            
            # Calcular duración total en segundos
            duration_multipliers = {'seconds': 1, 'minutes': 60, 'hours': 3600}
            total_duration = self.config.duration * duration_multipliers.get(self.config.duration_unit, 60)
            
            # Modo continuo con segmentación
            if self.config.continuous:
                # Patrón para archivos segmentados con timestamp
                self.filename = f"{self.camera_name}_%Y-%m-%d_%H-%M-%S.{self.config.format}"
                output_path = RECORDINGS_DIR / self.filename
                
                # Codec de video
                if self.config.codec == 'copy':
                    command.extend(['-c:v', 'copy'])
                else:
                    command.extend(['-c:v', self.config.codec])
                    if self.config.quality != 'auto':
                        command.extend(['-crf', self.config.quality])
                
                # Resolución
                if self.config.resolution != 'original' and self.config.codec != 'copy':
                    command.extend(['-vf', f'scale={self.config.resolution}'])
                
                # FPS
                if self.config.fps != 'original':
                    command.extend(['-r', self.config.fps])
                
                # Codec de audio con bitrate
                command.extend(['-c:a', 'aac', '-b:a', '128k'])
                
                # Configuración de segmentación
                segment_time = self.config.segment_duration * 60  # Convertir a segundos
                command.extend([
                    '-f', 'segment',
                    '-segment_time', str(segment_time),
                    '-strftime', '1',
                    '-reset_timestamps', '1'
                ])
                
                # Duración total si no es infinita
                if total_duration > 0:
                    command.extend(['-t', str(total_duration)])
                
            else:
                # Grabación normal de un solo archivo
                self.filename = f"{self.camera_name}_{timestamp}.{self.config.format}"
                output_path = RECORDINGS_DIR / self.filename
                
                # Añadir duración
                command.extend(['-t', str(total_duration)])
                
                # Codec de video
                if self.config.codec == 'copy':
                    command.extend(['-c:v', 'copy'])
                else:
                    command.extend(['-c:v', self.config.codec])
                    if self.config.quality != 'auto':
                        command.extend(['-crf', self.config.quality])
                
                # Resolución
                if self.config.resolution != 'original' and self.config.codec != 'copy':
                    command.extend(['-vf', f'scale={self.config.resolution}'])
                
                # FPS
                if self.config.fps != 'original':
                    command.extend(['-r', self.config.fps])
                
                # Codec de audio con bitrate
                command.extend(['-c:a', 'aac', '-b:a', '128k'])
            
            # Argumentos adicionales
            if self.config.extra_args:
                command.extend(self.config.extra_args.split())
            
            # Output
            command.append(str(output_path))
            
            print(f"🎥 Iniciando grabación: {' '.join(command)}")
            
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.is_recording = True
            self.start_time = datetime.now()
            
            # Thread para monitorear finalización
            threading.Thread(target=self._monitor_process, daemon=True).start()
            
            print(f"✅ Grabación iniciada: {self.filename}")
            return True
            
        except Exception as e:
            print(f"❌ Error iniciando grabación: {e}")
            return False
    
    def _monitor_process(self):
        """Monitorea el proceso de grabación"""
        self.process.wait()
        self.is_recording = False
        print(f"📼 Grabación finalizada: {self.filename}")
        
        # Eliminar de grabaciones activas
        if self.recording_id in active_recordings:
            del active_recordings[self.recording_id]
    
    def stop(self):
        """Detiene la grabación"""
        if not self.is_recording or not self.process:
            return False
        
        try:
            # Enviar señal de terminación suave
            self.process.terminate()
            
            # Esperar hasta 5 segundos
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # Si no termina, forzar
                self.process.kill()
                self.process.wait()
            
            self.is_recording = False
            print(f"⏹️ Grabación detenida: {self.filename}")
            return True
            
        except Exception as e:
            print(f"❌ Error deteniendo grabación: {e}")
            return False

def load_cameras_config():
    """Carga la configuración de cámaras desde archivo JSON"""
    if CAMERAS_CONFIG_FILE.exists():
        with open(CAMERAS_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_cameras_config(cameras: dict):
    """Guarda la configuración de cámaras en archivo JSON"""
    with open(CAMERAS_CONFIG_FILE, 'w') as f:
        json.dump(cameras, f, indent=2)

def scan_network_for_rtsp(network: str = "192.168.1.0/24") -> List[dict]:
    """Escanea la red buscando dispositivos con puertos RTSP abiertos"""
    try:
        nm = nmap.PortScanner()
        print(f"🔍 Escaneando red {network}...")
        
        # Escanear puertos RTSP comunes
        nm.scan(network, arguments='-p 554,8554,80 --open')
        
        cameras = []
        for host in nm.all_hosts():
            ports = []
            if nm[host].has_tcp(554) and nm[host]['tcp'][554]['state'] == 'open':
                ports.append(554)
            if nm[host].has_tcp(8554) and nm[host]['tcp'][8554]['state'] == 'open':
                ports.append(8554)
            if nm[host].has_tcp(80) and nm[host]['tcp'][80]['state'] == 'open':
                ports.append(80)
            
            if ports:
                cameras.append({
                    'ip': host,
                    'hostname': nm[host].hostname(),
                    'ports': ports
                })
                print(f"✅ Encontrado: {host} - Puertos: {ports}")
        
        return cameras
    except Exception as e:
        print(f"❌ Error escaneando red: {e}")
        return []

def get_rtsp_urls_from_onvif(ip: str, port: int, user: str, password: str) -> List[dict]:
    """Obtiene las URLs RTSP de una cámara ONVIF con información detallada"""
    try:
        cam = ONVIFCamera(ip, port, user, password)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        
        streams = []
        for idx, profile in enumerate(profiles):
            uri = media.GetStreamUri({
                'StreamSetup': {
                    'Stream': 'RTP-Unicast',
                    'Transport': {'Protocol': 'RTSP'}
                },
                'ProfileToken': profile.token
            })
            
            # Intentar obtener nombre del perfil
            profile_name = getattr(profile, 'Name', None) or f"Stream {idx + 1}"
            
            streams.append({
                'name': profile_name,
                'url': uri.Uri,
                'token': profile.token
            })
            print(f"  ✓ {profile_name}: {uri.Uri}")
        
        return streams
    except Exception as e:
        print(f"⚠️ Error obteniendo URLs ONVIF de {ip}: {e}")
        # Fallback a URL estándar
        return [{
            'name': 'Stream por defecto',
            'url': f"rtsp://{user}:{password}@{ip}:554/stream",
            'token': 'default'
        }]

def generate_frames(camera_id: str):
    """Generador de frames para streaming MJPEG usando FFmpeg"""
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
    """Inicializa las cámaras al arrancar la aplicación"""
    global CAMERAS
    CAMERAS = load_cameras_config()
    
    if not CAMERAS:
        print("⚠️ No hay cámaras configuradas. Accede a /setup para configurar.")
        return
    
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
            except Exception as e:
                print(f"⚠️ No se pudo iniciar {config['name']}: {e}")

@app.on_event("shutdown")
async def shutdown_event():
    """Liberar recursos al cerrar la aplicación"""
    for camera in active_cameras.values():
        await camera.close()

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Página principal con el visor de la cámara"""
    # Si no hay cámaras configuradas, redirigir a setup
    if not CAMERAS:
        return templates.TemplateResponse("setup.html", {"request": request})
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request):
    """Página de configuración de cámaras"""
    return templates.TemplateResponse("setup.html", {"request": request})

@app.get("/recording", response_class=HTMLResponse)
async def recording_page(request: Request):
    """Página de grabación de cámaras"""
    return templates.TemplateResponse("recording.html", {"request": request})

@app.get("/recordings_viewer", response_class=HTMLResponse)
async def recordings_viewer_page(request: Request):
    """Página de visualización de grabaciones"""
    return templates.TemplateResponse("recordings_viewer.html", {"request": request})

@app.get("/recordings/watch/{filename:path}", response_class=HTMLResponse)
async def watch_recording(request: Request, filename: str):
    """Página para reproducir una grabación específica"""
    recording_path = RECORDINGS_DIR / filename
    if recording_path.exists():
        return templates.TemplateResponse("watch.html", {"request": request, "video": filename})
    raise HTTPException(status_code=404, detail="Grabación no encontrada")

@app.get("/api/recordings/list")
async def list_recordings():
    """Lista todas las grabaciones guardadas"""
    try:
        recordings = []
        if RECORDINGS_DIR.exists():
            for file in RECORDINGS_DIR.iterdir():
                if file.is_file():
                    stats = file.stat()
                    recordings.append({
                        'filename': file.name,
                        'size': stats.st_size,
                        'modified': stats.st_mtime,
                        'format': file.suffix[1:] if file.suffix else 'unknown'
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

@app.get("/recordings/serve/{filename:path}")
async def serve_recording(filename: str, request: Request):
    """Sirve archivos de grabación con soporte de Range Requests para streaming"""
    try:
        from fastapi.responses import FileResponse
        import re
        
        file_path = RECORDINGS_DIR / filename
        
        if not file_path.exists():
            raise HTTPException(status_code=404, detail="Grabación no encontrada")
        
        file_size = file_path.stat().st_size
        
        # Obtener el tipo MIME
        import mimetypes
        mimetype = mimetypes.guess_type(filename)[0]
        if not mimetype:
            mimetype = 'video/mp4'
        
        # Parsear el header Range
        range_header = request.headers.get('range', None)
        
        if not range_header:
            # Sin range request, enviar archivo completo
            return FileResponse(
                str(file_path),
                media_type=mimetype,
                headers={
                    'Accept-Ranges': 'bytes',
                    'Content-Length': str(file_size)
                }
            )
        
        # Parsear el rango solicitado
        match = re.search(r'bytes=(\d+)-(\d*)', range_header)
        if not match:
            raise HTTPException(status_code=416, detail="Invalid Range header")
        
        start = int(match.group(1))
        end = int(match.group(2)) if match.group(2) else file_size - 1
        
        # Validar el rango
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(status_code=416, detail="Range Not Satisfiable")
        
        # Calcular la longitud del contenido a enviar
        content_length = end - start + 1
        
        # Leer la porción del archivo solicitada
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
        
        # Crear respuesta 206 Partial Content
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

@app.post("/api/scan")
async def scan_network(scan_req: ScanRequest):
    """Endpoint para escanear la red en busca de cámaras"""
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
    """Detecta los streams ONVIF disponibles de una cámara"""
    try:
        print(f"🔍 Detectando streams de {req.ip}...")
        streams = await asyncio.to_thread(
            get_rtsp_urls_from_onvif,
            req.ip,
            80,
            req.user,
            req.password
        )
        
        return JSONResponse({
            "success": True,
            "streams": streams
        })
    except Exception as e:
        return JSONResponse(
            {"success": False, "message": str(e), "streams": []},
            status_code=500
        )

@app.post("/api/cameras/setup")
async def setup_cameras(request: Request):
    """Configura las cámaras seleccionadas"""
    try:
        data = await request.json()
        cameras_data = data.get('cameras', [])
        
        global CAMERAS
        CAMERAS = {}
        
        for idx, cam_data in enumerate(cameras_data):
            camera_id = f"camera{idx + 1}"
            
            # Si ya se seleccionó un stream específico, usarlo
            if cam_data.get('stream_url'):
                rtsp_url = cam_data['stream_url']
                print(f"✓ Usando stream seleccionado: {rtsp_url}")
            else:
                # Intentar obtener URL RTSP usando ONVIF
                streams = await asyncio.to_thread(
                    get_rtsp_urls_from_onvif,
                    cam_data['ip'],
                    80,
                    cam_data['user'],
                    cam_data['password']
                )
                
                rtsp_url = streams[0]['url'] if streams else f"rtsp://{cam_data['user']}:{cam_data['password']}@{cam_data['ip']}:554/stream"
            
            CAMERAS[camera_id] = {
                "name": cam_data['name'],
                "url": rtsp_url,
                "enabled": True
            }
        
        # Guardar configuración
        save_cameras_config(CAMERAS)
        
        # Reiniciar cámaras
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

@app.post("/api/recording/start")
async def start_recording(config: RecordingConfig):
    """Inicia una nueva grabación"""
    try:
        # Verificar que la cámara existe
        if config.camera_id not in CAMERAS:
            return JSONResponse(
                {"success": False, "message": "Cámara no encontrada"},
                status_code=404
            )
        
        camera_config = CAMERAS[config.camera_id]
        recording_id = str(uuid.uuid4())
        
        # Crear recorder
        recorder = FFmpegRecorder(
            recording_id=recording_id,
            camera_id=config.camera_id,
            camera_name=camera_config['name'],
            rtsp_url=camera_config['url'],
            config=config
        )
        
        # Iniciar grabación en thread separado
        success = await asyncio.to_thread(recorder.start)
        
        if success:
            active_recordings[recording_id] = recorder
            return JSONResponse({
                "success": True,
                "recording_id": recording_id,
                "filename": recorder.filename
            })
        else:
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
    """Detiene una grabación activa"""
    try:
        if recording_id not in active_recordings:
            return JSONResponse(
                {"success": False, "message": "Grabación no encontrada"},
                status_code=404
            )
        
        recorder = active_recordings[recording_id]
        success = await asyncio.to_thread(recorder.stop)
        
        if success:
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
    """Lista todas las grabaciones activas"""
    recordings = []
    for rec_id, recorder in active_recordings.items():
        recordings.append({
            "id": rec_id,
            "camera_id": recorder.camera_id,
            "camera_name": recorder.camera_name,
            "filename": recorder.filename,
            "start_time": recorder.start_time.isoformat() if recorder.start_time else None,
            "is_recording": recorder.is_recording
        })
    
    return JSONResponse({"recordings": recordings})

@app.get("/video_feed/{camera_id}")
async def video_feed(camera_id: str):
    """Endpoint para el streaming MJPEG de una cámara específica"""
    if camera_id not in active_cameras:
        raise HTTPException(status_code=404, detail="Cámara no encontrada")
    
    return StreamingResponse(
        generate_frames(camera_id),
        media_type="multipart/x-mixed-replace; boundary=frame"
    )

@app.get("/api/cameras")
async def list_cameras():
    """Lista todas las cámaras disponibles"""
    cameras_info = {}
    for camera_id, camera in active_cameras.items():
        cameras_info[camera_id] = {
            "name": camera.name,
            "running": camera.is_running,
            "url": camera.rtsp_url
        }
    return cameras_info

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
