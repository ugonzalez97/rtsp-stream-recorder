"""
Class to handle RTSP camera streaming via FFmpeg
"""
import subprocess
import threading
from queue import Queue, Empty
from typing import Optional
import time


class FFmpegCamera:
    """Handles RTSP camera streaming using FFmpeg with low latency"""
    
    def __init__(self, camera_id: str, rtsp_url: str, name: str = "Camera"):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.name = name
        self.process: Optional[subprocess.Popen] = None
        self.is_running = False
        self.frame_queue: Queue = Queue(maxsize=2)  # Small buffer: only 2 frames
        self.reader_thread: Optional[threading.Thread] = None
        
    async def start(self):
        """Starts FFmpeg process to capture RTSP stream"""
        if self.is_running:
            return
            
        try:
            # FFmpeg command optimized for LOW LATENCY
            command = [
                'ffmpeg',
                # Low latency flags
                '-fflags', 'nobuffer',  # No buffering
                '-flags', 'low_delay',  # Low latency mode
                '-rtsp_transport', 'tcp',
                '-i', self.rtsp_url,
                # Minimal processing
                '-f', 'image2pipe',
                '-vcodec', 'mjpeg',
                '-q:v', '8',  # Medium quality for better speed
                '-vf', 'scale=1280:-1',  # Scale if too large
                '-r', '15',  # 15 FPS
                '-an',  # No audio (MJPEG video only)
                # More optimization flags
                '-probesize', '32',  # Reduce initial analysis
                '-analyzeduration', '0',  # Don't analyze duration
                '-'
            ]
            
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0  # No buffer in pipe
            )
            self.is_running = True
            
            # Start reader thread
            self.reader_thread = threading.Thread(target=self._read_frames, daemon=True)
            self.reader_thread.start()
            
            print(f"✅ FFmpeg iniciado para {self.name} ({self.camera_id}) - Modo baja latencia")
            
        except Exception as e:
            print(f"❌ Error iniciando FFmpeg para {self.name}: {e}")
            raise
    
    def _read_frames(self):
        """Thread that reads frames continuously and keeps only the most recent"""
        while self.is_running:
            try:
                frame = self._read_single_frame()
                if frame:
                    # If queue is full, discard old frame
                    while self.frame_queue.full():
                        try:
                            self.frame_queue.get_nowait()  # Discard old frame
                        except Empty:
                            break
                    
                    try:
                        self.frame_queue.put_nowait(frame)
                    except:
                        pass  # If can't add, continue
            except Exception as e:
                if self.is_running:
                    print(f"⚠️ Error en thread de lectura {self.name}: {e}")
                    time.sleep(0.1)
    
    def _read_single_frame(self) -> Optional[bytes]:
        """Reads a frame from FFmpeg process"""
        if not self.process or not self.is_running:
            return None
            
        try:
            # Look for JPEG start marker (FFD8)
            while True:
                byte = self.process.stdout.read(1)
                if not byte:
                    return None
                if byte == b'\xff':
                    byte2 = self.process.stdout.read(1)
                    if byte2 == b'\xd8':  # JPEG start
                        break
            
            # Read until JPEG end marker (FFD9)
            jpg = b'\xff\xd8'
            while True:
                byte = self.process.stdout.read(1)
                if not byte:
                    return None
                jpg += byte
                if len(jpg) >= 2 and jpg[-2:] == b'\xff\xd9':  # JPEG end
                    return jpg
                    
        except Exception as e:
            return None
    
    def read_frame(self) -> Optional[bytes]:
        """Gets the most recent frame from queue (discarding old ones if any)"""
        if not self.is_running:
            return None
        
        try:
            # Get most recent frame, discarding old ones if several exist
            frame = None
            while True:
                try:
                    frame = self.frame_queue.get(timeout=0.5)
                    # If more frames in queue, get next (more recent)
                    if not self.frame_queue.empty():
                        continue
                    break
                except Empty:
                    # If no frames, return the last one we had
                    break
            return frame
        except Exception as e:
            return None
    
    async def close(self):
        """Closes FFmpeg process"""
        self.is_running = False
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
            self.process = None
        print(f"🔌 FFmpeg detenido para {self.name}")
