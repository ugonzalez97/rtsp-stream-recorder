"""
Class to handle RTSP stream recording via FFmpeg
"""
import subprocess
import threading
from pathlib import Path
from typing import Optional, Dict
from datetime import datetime
from models import RecordingConfig
from logger import setup_logger

# Setup logger
logger = setup_logger(__name__)


# Recordings directory
RECORDINGS_DIR = Path("recordings")
RECORDINGS_DIR.mkdir(exist_ok=True)


class FFmpegRecorder:
    """Handles RTSP camera recording using FFmpeg"""
    
    def __init__(
        self, 
        recording_id: str, 
        camera_id: str, 
        camera_name: str, 
        rtsp_url: str, 
        config: RecordingConfig,
        camera_info: Dict = None
    ):
        self.recording_id = recording_id
        self.camera_id = camera_id
        self.camera_name = camera_name
        self.rtsp_url = rtsp_url
        self.config = config
        self.camera_info = camera_info or {}
        self.process: Optional[subprocess.Popen] = None
        self.is_recording = False
        self.start_time = None
        self.filename = None
        
    def start(self):
        """Starts recording"""
        if self.is_recording:
            return False
        
        try:
            max_res = self.camera_info.get('max_resolution', {'width': 1920, 'height': 1080})
            max_fps = self.camera_info.get('max_fps', 30)

            # Adjust requested resolution to not exceed camera capability
            effective_resolution = None
            if self.config.resolution != 'original':
                try:
                    req_width, req_height = map(int, self.config.resolution.split('x'))
                    clamped_width = min(req_width, max_res.get('width', req_width))
                    clamped_height = min(req_height, max_res.get('height', req_height))
                    effective_resolution = f"{clamped_width}x{clamped_height}"
                except ValueError:
                    effective_resolution = None

            # Adjust requested FPS to not exceed camera limit
            effective_fps = None
            if self.config.fps != 'original':
                try:
                    requested_fps = int(self.config.fps)
                    effective_fps = min(requested_fps, max_fps) if max_fps else requested_fps
                except ValueError:
                    effective_fps = None

            # Generate filename
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            
            # Build FFmpeg command
            command = [
                'ffmpeg',
                '-rtsp_transport', 'tcp',
                '-i', self.rtsp_url,
            ]
            
            # Calculate total duration in seconds
            duration_multipliers = {'seconds': 1, 'minutes': 60, 'hours': 3600}
            total_duration = self.config.duration * duration_multipliers.get(self.config.duration_unit, 60)
            
            # Continuous mode with segmentation
            if self.config.continuous:
                # Pattern for segmented files with timestamp
                self.filename = f"{self.camera_name}_%Y-%m-%d_%H-%M-%S.{self.config.format}"
                output_path = RECORDINGS_DIR / self.filename
                
                # Video codec
                if self.config.codec == 'copy':
                    command.extend(['-c:v', 'copy'])
                else:
                    command.extend(['-c:v', self.config.codec])
                    if self.config.quality != 'auto':
                        command.extend(['-crf', self.config.quality])
                
                # Resolution
                if effective_resolution and self.config.codec != 'copy':
                    command.extend(['-vf', f'scale={effective_resolution}'])
                
                # FPS
                if effective_fps and self.config.codec != 'copy':
                    command.extend(['-r', str(effective_fps)])
                
                # Audio codec with bitrate
                command.extend(['-c:a', 'aac', '-b:a', '128k'])
                
                # Segmentation configuration
                segment_time = self.config.segment_duration  # Already in seconds
                command.extend([
                    '-f', 'segment',
                    '-segment_time', str(segment_time),
                    '-strftime', '1',
                    '-reset_timestamps', '1'
                ])
                
            else:
                # Normal recording to single file
                self.filename = f"{self.camera_name}_{timestamp}.{self.config.format}"
                output_path = RECORDINGS_DIR / self.filename
                
                # Add duration
                command.extend(['-t', str(total_duration)])
                
                # Video codec
                if self.config.codec == 'copy':
                    command.extend(['-c:v', 'copy'])
                else:
                    command.extend(['-c:v', self.config.codec])
                    if self.config.quality != 'auto':
                        command.extend(['-crf', self.config.quality])
                
                # Resolution
                if effective_resolution and self.config.codec != 'copy':
                    command.extend(['-vf', f'scale={effective_resolution}'])
                
                # FPS
                if effective_fps and self.config.codec != 'copy':
                    command.extend(['-r', str(effective_fps)])
                
                # Codec de audio con bitrate
                command.extend(['-c:a', 'aac', '-b:a', '128k'])
            
            # Additional arguments
            if self.config.extra_args:
                command.extend(self.config.extra_args.split())
            
            # Output
            command.append(str(output_path))
            
            logger.info(f"Starting recording: {self.camera_name}")
            logger.debug(f"FFmpeg command: {' '.join(command)}")
            
            self.process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            self.is_recording = True
            self.start_time = datetime.now()
            
            logger.info(f"Recording started successfully: {self.filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start recording for {self.camera_name}: {e}")
            return False
    
    def stop(self):
        """Stops recording"""
        if not self.is_recording or not self.process:
            return False
        
        try:
            # Send gentle termination signal
            self.process.terminate()
            
            # Wait up to 5 seconds
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                # If doesn't finish, force kill
                self.process.kill()
                self.process.wait()
            
            self.is_recording = False
            logger.info(f"Recording stopped: {self.filename}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to stop recording {self.filename}: {e}")
            return False
    
    def is_still_recording(self) -> bool:
        """Check if the recording process is still running"""
        if not self.process:
            return False
        
        # Check if process is still alive
        poll = self.process.poll()
        if poll is not None:
            # Process has finished
            self.is_recording = False
            logger.info(f"Recording completed naturally: {self.filename}")
            return False
        
        return True
