"""
Pydantic models for data validation
"""
from pydantic import BaseModel
from typing import Optional


class CameraSetup(BaseModel):
    """Model for camera setup"""
    ip: str
    name: str
    user: str
    password: str
    stream_url: Optional[str] = None


class ScanRequest(BaseModel):
    """Model for network scan request"""
    network: str = "192.168.1.0/24"


class DetectStreamsRequest(BaseModel):
    """Model for ONVIF stream detection"""
    ip: str
    user: str
    password: str


class RecordingConfig(BaseModel):
    """Model for recording configuration"""
    camera_id: str
    resolution: str = "original"
    fps: str = "original"
    duration: int = 10
    duration_unit: str = "minutes"  # seconds, minutes, hours
    codec: str = "copy"
    quality: str = "auto"
    format: str = "mp4"
    extra_args: str = ""
    continuous: bool = False  # Continuous recording with segments
    segment_duration: int = 15  # Duration of each segment in minutes (for continuous mode)
