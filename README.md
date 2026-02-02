# 🎥 RTSP Stream Recorder

A simple web app to view and record RTSP camera streams using FastAPI and FFmpeg.

## Features

- 📹 Live view of multiple IP cameras with low latency
- 🎬 Record streams with custom quality settings
- 🔄 Continuous recording mode with auto file segmentation
- 🔍 Network scan to find cameras automatically
- 🎯 ONVIF support for easy camera setup
- 📦 Multiple output formats (MP4, MKV, TS)

## Quick Start

### Requirements

- Python 3.8+
- FFmpeg
- nmap

### Install

```bash
# Install system dependencies (Ubuntu/Debian)
sudo apt install python3-pip ffmpeg nmap

# Clone and setup
git clone git@github.com:ugonzalez97/rtsp-stream-recorder.git
cd rtsp-stream-recorder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Run

```bash
python src/app.py
```

Go to http://localhost:8000

## How to Use

1. **Setup cameras**: Go to `/setup` and scan your network or manually add cameras
2. **Watch live**: Main page shows all cameras in real-time
3. **Record**: Go to `/recording`, select cameras and configure recording options
4. **View recordings**: Check `/recordings_viewer` to watch saved videos

## Project Structure

```
rtsp-stream-recorder/
├── src/
│   ├── app.py              # Main FastAPI app
│   ├── models.py           # Pydantic models
│   ├── camera.py           # Camera streaming class
│   ├── recorder.py         # Recording class
│   ├── config.py           # Config management
│   └── network_utils.py    # Network scanning & ONVIF
├── templates/              # HTML templates
├── recordings/             # Saved recordings
└── cameras_config.json     # Camera config (auto-generated)
```

## Recording Modes

**Normal Mode**: Records one file for the specified duration
```
Duration: 10 minutes → one_file.mp4 (10 min)
```

**Continuous Mode**: Creates segments until you stop it
```
Segment: 15 minutes → 
  camera1_2026-02-02_20-00-00.mp4
  camera1_2026-02-02_20-15-00.mp4
  camera1_2026-02-02_20-30-00.mp4
  ...
```

## Configuration

You can tweak recording settings:
- Resolution (original, 1080p, 720p, 480p, 360p)
- FPS (original, 30, 25, 20, 15, 10)
- Codec (copy, H.264, H.265)
- Quality (CRF 18-28)
- Custom FFmpeg args

## Troubleshooting

**Camera won't connect?**
- Check the RTSP URL is correct
- Verify username/password
- Make sure port 554 is open

**FFmpeg not found?**
```bash
ffmpeg -version  # check if installed
```

**High latency?**
- Reduce resolution in settings
- Use "copy" codec to avoid re-encoding

## API Endpoints

Main endpoints:
- `GET /` - Live viewer
- `GET /video_feed/{camera_id}` - MJPEG stream
- `POST /api/recording/start` - Start recording
- `POST /api/recording/stop/{id}` - Stop recording
- `GET /api/recordings/list` - List saved recordings

## Security Note

⚠️ This is meant for local networks. Don't expose it to the internet without adding authentication!

## License

MIT

---

Made with ❤️ for home surveillance needs
