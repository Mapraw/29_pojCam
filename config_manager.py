import json
from pathlib import Path
from typing import Dict, Any

BASE_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BASE_DIR / "config.json"

DEFAULT_CONFIG: Dict[str, Any] = {
    "rtsp_url": "rtsp://cam_poj01:12345678@192.168.1.238:554/stream1",
    "storage_limit_gb": 8.0,
    "quality_profile": "480p_10fps",  # 480p_10fps, 720p_native, 1080p_full, 360p_10fps
    "segment_duration_seconds": 900
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
    """Loads configuration from config.json with fallback to default_url or high_qual.txt."""
    config = DEFAULT_CONFIG.copy()

    # Load high_qual.txt if present
    txt_url_file = BASE_DIR / "high_qual.txt"
    if txt_url_file.exists():
        try:
            url = txt_url_file.read_text().strip()
            if url:
                config["rtsp_url"] = url
        except Exception:
            pass

    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r") as f:
                saved = json.load(f)
                config.update(saved)
        except Exception as e:
            print(f"[ConfigManager] Error reading config.json: {e}")

    return config


def save_config(new_config: Dict[str, Any]) -> Dict[str, Any]:
    """Saves updated config to config.json and updates high_qual.txt."""
    config = load_config()
    config.update(new_config)

    try:
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        # Sync high_qual.txt if url changed
        if "rtsp_url" in new_config and new_config["rtsp_url"]:
            txt_url_file = BASE_DIR / "high_qual.txt"
            txt_url_file.write_text(new_config["rtsp_url"].strip())

    except Exception as e:
        print(f"[ConfigManager] Error saving config.json: {e}")

    return config
