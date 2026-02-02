"""
Camera configuration management
"""
import json
from pathlib import Path
from typing import Dict


CAMERAS_CONFIG_FILE = Path("cameras_config.json")


def load_cameras_config() -> Dict:
    """Loads camera configuration from JSON file"""
    if CAMERAS_CONFIG_FILE.exists():
        with open(CAMERAS_CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {}


def save_cameras_config(cameras: dict) -> None:
    """Saves camera configuration to JSON file"""
    with open(CAMERAS_CONFIG_FILE, 'w') as f:
        json.dump(cameras, f, indent=2)
