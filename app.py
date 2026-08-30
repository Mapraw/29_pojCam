import os
import sys
import time
import re
import json
import threading
import webbrowser
import cv2
from pathlib import Path
from flask import Flask, Response, render_template, request, jsonify, send_file, send_from_directory, abort

from stream_manager import RTSPStreamManager, SNAPSHOTS_DIR, RECORDINGS_DIR
from storage_manager import StorageManager, THUMBNAILS_DIR
from recorder import ContinuousNVRRecorder
from system_info import get_system_metrics
from config_manager import load_config, save_config, QUALITY_PROFILES

app = Flask(__name__)

# Initialize Config & Managers
app_config = load_config()
initial_storage_bytes = int(app_config.get("storage_limit_gb", 8.0) * 1024 * 1024 * 1024)
storage_mgr = StorageManager(recordings_dir=RECORDINGS_DIR, max_storage_bytes=initial_storage_bytes)
stream_mgr = RTSPStreamManager()
nvr_recorder = ContinuousNVRRecorder(
    rtsp_url=stream_mgr.rtsp_url,
    storage_mgr=storage_mgr,
    segment_duration=app_config.get("segment_duration_seconds", 900),
    quality_profile=app_config.get("quality_profile", "480p_10fps")
)

def generate_mjpeg():
    """Generator function that produces MJPEG stream frames."""
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
    while True:
        frame = stream_mgr.get_latest_frame()
        ret, buffer = cv2.imencode('.jpg', frame, encode_param)
        if not ret:
            time.sleep(0.03)
            continue
        
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n'
               b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' + 
               frame_bytes + b'\r\n')
        time.sleep(0.02)  # Yield at ~40-50 fps max to save CPU

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/video_feed')
def video_feed():
    return Response(generate_mjpeg(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/api/status')
def api_status():
    status = stream_mgr.get_status()
    status["storage"] = storage_mgr.get_storage_info()
    status["system"] = get_system_metrics()
    status["nvr_status"] = nvr_recorder.status
    return jsonify(status)

@app.route('/api/storage')
def api_storage():
    return jsonify(storage_mgr.get_storage_info())

@app.route('/api/system')
def api_system():
    return jsonify(get_system_metrics())

@app.route('/api/clips')
def api_clips():
    """Lists all 15-minute video clips with metadata, thumbnails, lock status, and motion flags."""
    clips = []
    now_ts = time.time()
    video_files = list(RECORDINGS_DIR.glob("*.mp4")) + list(RECORDINGS_DIR.glob("*.mkv"))
    video_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    active_clip = nvr_recorder.get_active_recording_info()
    active_filename = active_clip["filename"] if active_clip else None

    for vf in video_files:
        filename = vf.name
        # Skip the active recording file from completed list
        if active_filename and filename == active_filename:
            continue

        size_bytes = vf.stat().st_size
        # Skip empty or 0-byte files
        if size_bytes < 1000:
            continue

        mtime = vf.stat().st_mtime
        size_mb = round(size_bytes / (1024 * 1024), 2)
        meta = storage_mgr.get_clip_meta(filename)
        time_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(mtime))
        date_group = time.strftime("%Y-%m-%d", time.localtime(mtime))

        thumb_file = f"{vf.stem}.jpg"
        thumb_path = THUMBNAILS_DIR / thumb_file
        has_thumb = thumb_path.exists()

        if not has_thumb and size_bytes > 2000:
            has_thumb = nvr_recorder._generate_thumbnail(vf, thumb_path)

        clips.append({
            "filename": filename,
            "size_mb": size_mb,
            "timestamp": time_str,
            "date_group": date_group,
            "thumbnail_url": f"/api/thumbnails/{thumb_file}" if has_thumb else "/static/placeholder_thumb.jpg",
            "video_url": f"/api/clips/{filename}",
            "locked": meta.get("locked", False),
            "has_motion": meta.get("has_motion", False),
            "motion_events": meta.get("motion_events", 0),
            "motion_timestamps": meta.get("motion_timestamps", [])
        })

    return jsonify({
        "clips": clips,
        "active_clip": active_clip,
        "storage": storage_mgr.get_storage_info(),
        "nvr_status": nvr_recorder.status
    })

@app.route('/api/record/split', methods=['POST'])
def api_record_split():
    """Finalizes the currently active recording segment into a completed clip and starts next."""
    success = nvr_recorder.split_segment()
    return jsonify({"success": success, "message": "Clip finalized and saved to archive!"})

@app.route('/api/clips/<path:filename>')
def serve_video_stream(filename):
    """
    Serves MP4 video with HTTP 206 Partial Content (Range Requests) support.
    Essential for instant seek/scrubbing in iOS Safari, Android Chrome, and desktop browsers.
    """
    file_path = RECORDINGS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        abort(404)

    file_size = file_path.stat().st_size
    range_header = request.headers.get('Range', None)

    if not range_header:
        # Standard full file response
        return send_file(file_path, mimetype='video/mp4')

    # Parse byte range
    byte_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not byte_match:
        return send_file(file_path, mimetype='video/mp4')

    start_byte = int(byte_match.group(1))
    end_byte_str = byte_match.group(2)
    end_byte = int(end_byte_str) if end_byte_str else file_size - 1

    if start_byte >= file_size:
        return Response(status=416)  # Range not satisfiable

    length = end_byte - start_byte + 1

    def stream_chunk():
        with open(file_path, 'rb') as f:
            f.seek(start_byte)
            remaining = length
            chunk_size = 64 * 1024  # 64 KB chunks
            while remaining > 0:
                read_size = min(chunk_size, remaining)
                data = f.read(read_size)
                if not data:
                    break
                remaining -= len(data)
                yield data

    response = Response(stream_chunk(), 206, mimetype='video/mp4', direct_passthrough=True)
    response.headers.add('Content-Range', f'bytes {start_byte}-{end_byte}/{file_size}')
    response.headers.add('Accept-Ranges', 'bytes')
    response.headers.add('Content-Length', str(length))
    return response

@app.route('/api/thumbnails/<path:filename>')
def serve_thumbnail(filename):
    return send_from_directory(THUMBNAILS_DIR, filename)

@app.route('/api/clips/lock', methods=['POST'])
def api_clip_lock():
    data = request.json or {}
    filename = data.get("filename")
    locked = data.get("locked", True)
    if not filename:
        return jsonify({"success": False, "error": "Filename required"}), 400

    new_state = storage_mgr.set_locked(filename, bool(locked))
    return jsonify({"success": True, "filename": filename, "locked": new_state})

@app.route('/api/clips/delete', methods=['POST'])
def api_clip_delete():
    data = request.json or {}
    filename = data.get("filename")
    if not filename:
        return jsonify({"success": False, "error": "Filename required"}), 400

    success = storage_mgr.delete_clip(filename)
    return jsonify({"success": success, "storage": storage_mgr.get_storage_info()})

@app.route('/api/snapshot', methods=['POST'])
def api_snapshot():
    try:
        filename = stream_mgr.capture_snapshot()
        return jsonify({"success": True, "filename": filename, "url": f"/snapshots/{filename}"})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

@app.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    return send_from_directory(SNAPSHOTS_DIR, filename)

@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        config = load_config()
        return jsonify({
            "config": config,
            "quality_profiles": QUALITY_PROFILES,
            "current_quality": nvr_recorder.quality_profile,
            "current_storage_limit_gb": round(storage_mgr.max_storage_bytes / (1024 * 1024 * 1024), 1),
            "status": stream_mgr.get_status()
        })

    data = request.json or {}
    config_updates = {}

    # 1. Handle Storage Limit change (e.g. 8.0 GB)
    if "storage_limit_gb" in data:
        try:
            new_gb = float(data["storage_limit_gb"])
            if new_gb >= 1.0:
                storage_mgr.set_max_storage_gb(new_gb)
                config_updates["storage_limit_gb"] = new_gb
        except Exception as e:
            print(f"[API Settings] Storage limit error: {e}")

    # 2. Handle Quality Profile change (e.g. 480p_10fps)
    if "quality_profile" in data and data["quality_profile"] in QUALITY_PROFILES:
        new_profile = data["quality_profile"]
        nvr_recorder.set_quality_profile(new_profile)
        config_updates["quality_profile"] = new_profile

    # 3. Handle RTSP URL change
    if "rtsp_url" in data and data["rtsp_url"] != stream_mgr.rtsp_url:
        new_url = data["rtsp_url"].strip()
        stream_mgr.save_url(new_url)
        nvr_recorder.restart(new_url)
        config_updates["rtsp_url"] = new_url

    # Save to config.json
    if config_updates:
        save_config(config_updates)

    stream_mgr.update_settings(
        transport=data.get("transport"),
        brightness=data.get("brightness"),
        contrast=data.get("contrast"),
        flip_h=data.get("flip_h"),
        flip_v=data.get("flip_v"),
        rotate=data.get("rotate_angle")
    )

    return jsonify({
        "success": True,
        "config": load_config(),
        "storage": storage_mgr.get_storage_info(),
        "status": stream_mgr.get_status()
    })

def find_available_port(start_port=5000, max_attempts=10):
    import socket
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    return start_port

if __name__ == '__main__':
    stream_mgr.start()
    nvr_recorder.start()
    
    port = find_available_port(5000)
    url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f"  🍓 Raspberry Pi RTSP NVR & Web Server Active")
    print(f"  Target RTSP: {stream_mgr.rtsp_url}")
    print(f"  Max Storage Pool: {storage_mgr.max_storage_bytes / (1024*1024*1024):.1f} GB (15-min segments)")
    print(f"  Open Web UI: {url}")
    print(f"=======================================================\n")
    
    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    finally:
        nvr_recorder.stop()
        stream_mgr.stop()
