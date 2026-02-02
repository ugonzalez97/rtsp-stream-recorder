"""
Utilities for network scanning and ONVIF detection
"""
import nmap
from onvif import ONVIFCamera
from typing import List, Dict


def scan_network_for_rtsp(network: str = "192.168.1.0/24") -> List[dict]:
    """Scans network looking for devices with open RTSP ports"""
    try:
        nm = nmap.PortScanner()
        print(f"🔍 Escaneando red {network}...")
        
        # Scan common RTSP ports
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
    """Gets RTSP URLs from an ONVIF camera with detailed information"""
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
            
            # Try to get profile name
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
        # Fallback to standard URL
        return [{
            'name': 'Stream por defecto',
            'url': f"rtsp://{user}:{password}@{ip}:554/stream",
            'token': 'default'
        }]


def get_camera_info_from_onvif(ip: str, port: int, user: str, password: str) -> Dict:
    """Gets detailed camera information (resolution, fps, bitrate, codec)"""
    try:
        cam = ONVIFCamera(ip, port, user, password)
        media = cam.create_media_service()
        profiles = media.GetProfiles()
        
        camera_info = {
            'profiles': [],
            'max_resolution': {'width': 0, 'height': 0},
            'max_fps': 0,
            'codecs': set()
        }
        
        for profile in profiles:
            try:
                cfg = media.GetVideoEncoderConfiguration(
                    {'ConfigurationToken': profile.VideoEncoderConfiguration.token}
                )
                
                profile_info = {
                    'name': getattr(profile, 'Name', 'Unknown'),
                    'codec': str(cfg.Encoding),
                    'resolution': {
                        'width': cfg.Resolution.Width,
                        'height': cfg.Resolution.Height
                    },
                    'fps': cfg.RateControl.FrameRateLimit,
                    'bitrate': cfg.RateControl.BitrateLimit
                }
                
                camera_info['profiles'].append(profile_info)
                camera_info['codecs'].add(str(cfg.Encoding))
                
                # Update maximums
                if cfg.Resolution.Width > camera_info['max_resolution']['width']:
                    camera_info['max_resolution'] = {
                        'width': cfg.Resolution.Width,
                        'height': cfg.Resolution.Height
                    }
                
                if cfg.RateControl.FrameRateLimit > camera_info['max_fps']:
                    camera_info['max_fps'] = cfg.RateControl.FrameRateLimit
                    
            except Exception as e:
                print(f"⚠️ Error obteniendo info del perfil: {e}")
                continue
        
        camera_info['codecs'] = list(camera_info['codecs'])
        return camera_info
        
    except Exception as e:
        print(f"⚠️ Error obteniendo info de cámara {ip}: {e}")
        return {
            'profiles': [],
            'max_resolution': {'width': 1920, 'height': 1080},
            'max_fps': 30,
            'codecs': ['H264']
        }
