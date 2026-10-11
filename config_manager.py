import json
import re
from pathlib import Path
from typing import Dict, Any, List, Optional

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"
DEFAULT_URL_FILE = BASE_DIR / "high_qual.txt"
CAMERA2_URL_FILE = BASE_DIR / "camera2.txt"

DEFAULT_CAMERAS: List[Dict[str, Any]] = [
    {
        "id": "cam1",
        "name": "Camera 1 (Poj 01)",
        "rtsp_url": "rtsp://cam_poj01:12345678@192.168.1.238:554/stream2",
        "image": "/static/mascot_cam1.jpg",
        "enabled": True
    },
    {
        "id": "cam2",
        "name": "Camera 2 (Poj 02)",
        "rtsp_url": "rtsp://campoj2:campoj2@192.168.1.247/stream2",
        "image": "/static/mascot_cam2.jpg",
        "enabled": True
    }
]

DEFAULT_CONFIG: Dict[str, Any] = {
    "storage_limit_gb": 8.0,
    "quality_profile": "480p_10fps",  # 480p_10fps, 720p_native, 1080p_full, 360p_10fps
    "segment_duration_seconds": 900,
    "active_camera": "cam1",
    "cameras": DEFAULT_CAMERAS
}

QUALITY_PROFILES = {
    "480p_10fps": {
        "label": "480p @ 10 FPS (Recommended - ~3.9 Days in 8GB)",
        "resolution": "854x480",
        "fps": 10,
        "video_bitrate": "220k",
        "audio_bitrate": "32k",
        "transcode": True,
        "est_gb_per_day": 2.06,
        "est_days_8gb": 3.9
    },
    "360p_10fps": {
        "label": "360p @ 10 FPS (Ultra Economy - ~5.0 Days in 8GB)",
        "resolution": "640x360",
        "fps": 10,
        "video_bitrate": "150k",
        "audio_bitrate": "32k",
        "transcode": True,
        "est_gb_per_day": 1.60,
        "est_days_8gb": 5.0
    },
    "720p_native": {
        "label": "720p HD @ 15 FPS (Native Substream - ~1.7 Days in 8GB)",
        "resolution": "1280x720",
        "fps": 15,
        "transcode": False,
        "use_stream2": True,
        "est_gb_per_day": 4.68,
        "est_days_8gb": 1.7
    },
    "1080p_full": {
        "label": "1080p Full HD @ 15 FPS (Maximum Quality - ~12 Hours in 8GB)",
        "resolution": "1920x1080",
        "fps": 15,
        "transcode": False,
        "use_stream2": False,
        "est_gb_per_day": 15.73,
        "est_days_8gb": 0.5
    }
}


def load_config() -> Dict[str, Any]:
    """Loads configuration from config.json with fallback to default_url or high_qual.txt and camera2.txt."""
    config = {
        "storage_limit_gb": DEFAULT_CONFIG["storage_limit_gb"],
        "quality_profile": DEFAULT_CONFIG["quality_profile"],
        "segment_duration_seconds": DEFAULT_CONFIG["segment_duration_seconds"],
        "active_camera": DEFAULT_CONFIG["active_camera"],
        "cameras": [cam.copy() for cam in DEFAULT_CAMERAS]
    }

    # Load high_qual.txt if present for cam1
    if DEFAULT_URL_FILE.exists():
        try:
            url = DEFAULT_URL_FILE.read_text(encoding="utf-8").strip()
            if url:
                config["cameras"][0]["rtsp_url"] = url
        except Exception:
            pass

    # Load camera2.txt if present for cam2
    if CAMERA2_URL_FILE.exists():
        try:
            url = CAMERA2_URL_FILE.read_text(encoding="utf-8").strip()
            if url and len(config["cameras"]) > 1:
                config["cameras"][1]["rtsp_url"] = url
        except Exception:
            pass

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                saved = json.load(f)
                # Handle legacy single-camera config
                if "cameras" not in saved and "rtsp_url" in saved:
                    config["cameras"][0]["rtsp_url"] = saved["rtsp_url"]
                    del saved["rtsp_url"]
                config.update(saved)
        except Exception as e:
            print(f"[ConfigManager] Error reading config.json: {e}")

    # Ensure backward compatibility: rtsp_url top-level field
    active_cam_id = config.get("active_camera", "cam1")
    active_cam = next((c for c in config.get("cameras", []) if c.get("id") == active_cam_id), None)
    if active_cam:
        config["rtsp_url"] = active_cam.get("rtsp_url", "")
    elif config.get("cameras"):
        config["rtsp_url"] = config["cameras"][0].get("rtsp_url", "")

    return config


def save_config(new_config: Dict[str, Any]) -> Dict[str, Any]:
    """Saves updated config to config.json and syncs text files."""
    config = load_config()
    config.update(new_config)

    # Sync top-level rtsp_url
    active_cam_id = config.get("active_camera", "cam1")
    active_cam = next((c for c in config.get("cameras", []) if c.get("id") == active_cam_id), None)
    if active_cam:
        config["rtsp_url"] = active_cam.get("rtsp_url", "")

    try:
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, indent=2)

        # Sync text files
        for cam in config.get("cameras", []):
            if cam.get("id") == "cam1" and cam.get("rtsp_url"):
                DEFAULT_URL_FILE.write_text(cam["rtsp_url"].strip(), encoding="utf-8")
            elif cam.get("id") == "cam2" and cam.get("rtsp_url"):
                CAMERA2_URL_FILE.write_text(cam["rtsp_url"].strip(), encoding="utf-8")

    except Exception as e:
        print(f"[ConfigManager] Error saving config.json: {e}")

    return config


def get_cameras() -> List[Dict[str, Any]]:
    """Returns list of all configured cameras."""
    cfg = load_config()
    return cfg.get("cameras", [])


def get_camera(cam_id: str) -> Optional[Dict[str, Any]]:
    """Returns a specific camera configuration by ID."""
    cameras = get_cameras()
    return next((c for c in cameras if c.get("id") == cam_id), None)


def add_camera(name: str, rtsp_url: str, image: Optional[str] = None) -> Dict[str, Any]:
    """Adds a new camera and persists to config.json."""
    config = load_config()
    cameras = config.get("cameras", [])

    # Generate unique ID
    existing_nums = []
    for c in cameras:
        m = re.search(r'\d+', c.get("id", ""))
        if m:
            existing_nums.append(int(m.group(0)))
    next_num = max(existing_nums, default=0) + 1
    new_id = f"cam{next_num}"

    new_cam = {
        "id": new_id,
        "name": name.strip() or f"Camera {next_num}",
        "rtsp_url": rtsp_url.strip(),
        "image": image or "/static/mascot_default.jpg",
        "enabled": True
    }
    cameras.append(new_cam)
    config["cameras"] = cameras
    save_config(config)
    return new_cam


def update_camera(cam_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Updates an existing camera configuration."""
    config = load_config()
    cameras = config.get("cameras", [])
    target = None
    for c in cameras:
        if c.get("id") == cam_id:
            if "name" in updates and updates["name"]:
                c["name"] = updates["name"].strip()
            if "rtsp_url" in updates and updates["rtsp_url"]:
                c["rtsp_url"] = updates["rtsp_url"].strip()
            if "image" in updates and updates["image"]:
                c["image"] = updates["image"].strip()
            if "enabled" in updates:
                c["enabled"] = bool(updates["enabled"])
            target = c
            break

    if target:
        config["cameras"] = cameras
        save_config(config)
    return target


def delete_camera(cam_id: str) -> bool:
    """Removes a camera from config."""
    config = load_config()
    cameras = config.get("cameras", [])
    initial_len = len(cameras)
    cameras = [c for c in cameras if c.get("id") != cam_id]

    if len(cameras) < initial_len:
        config["cameras"] = cameras
        if config.get("active_camera") == cam_id and cameras:
            config["active_camera"] = cameras[0]["id"]
        save_config(config)
        return True
    return False
