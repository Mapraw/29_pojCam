import os
import sys
import time
import re
import json
import threading
import webbrowser
import cv2
from pathlib import Path
from typing import Dict, Any, Optional

# Force UTF-8 encoding on Windows to prevent UnicodeEncodeError on cp874/cp1252 consoles
if sys.platform.startswith("win"):
    import io
    if hasattr(sys.stdout, 'buffer') and getattr(sys.stdout, 'encoding', '').lower() != 'utf-8':
        try:
            sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass
    if hasattr(sys.stderr, 'buffer') and getattr(sys.stderr, 'encoding', '').lower() != 'utf-8':
        try:
            sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')
        except Exception:
            pass

from flask import Flask, Response, render_template, request, jsonify, send_file, send_from_directory, abort

from stream_manager import RTSPStreamManager, SNAPSHOTS_DIR, RECORDINGS_DIR
from storage_manager import StorageManager, THUMBNAILS_DIR
from recorder import ContinuousNVRRecorder
from system_info import get_system_metrics
from config_manager import (
    load_config, save_config, get_cameras, get_camera,
    add_camera, update_camera, delete_camera, QUALITY_PROFILES
)

app = Flask(__name__)

# Initialize Config & Shared Storage
app_config = load_config()
initial_storage_bytes = int(app_config.get("storage_limit_gb", 8.0) * 1024 * 1024 * 1024)
storage_mgr = StorageManager(recordings_dir=RECORDINGS_DIR, max_storage_bytes=initial_storage_bytes)

# Multi-Camera Service Registries
stream_managers: Dict[str, RTSPStreamManager] = {}
nvr_recorders: Dict[str, ContinuousNVRRecorder] = {}
services_lock = threading.Lock()


def sync_camera_services():
    """Synchronizes running RTSPStreamManagers and ContinuousNVRRecorders with config.json."""
    with services_lock:
        config = load_config()
        configured_cams = {c["id"]: c for c in config.get("cameras", [])}
        quality = config.get("quality_profile", "480p_10fps")
        seg_duration = config.get("segment_duration_seconds", 900)

        # 1. Stop and remove services for removed cameras
        for cam_id in list(stream_managers.keys()):
            if cam_id not in configured_cams:
                print(f"[App] Shutting down removed camera: {cam_id}")
                if cam_id in nvr_recorders:
                    try:
                        nvr_recorders[cam_id].stop()
                    except Exception as e:
                        print(f"[App] Error stopping recorder {cam_id}: {e}")
                    del nvr_recorders[cam_id]
                if cam_id in stream_managers:
                    try:
                        stream_managers[cam_id].stop()
                    except Exception as e:
                        print(f"[App] Error stopping stream {cam_id}: {e}")
                    del stream_managers[cam_id]

        # 2. Add or update services for configured cameras
        for cam_id, cam_info in configured_cams.items():
            rtsp_url = cam_info.get("rtsp_url", "").strip()
            if not rtsp_url:
                continue

            # Stream Manager
            if cam_id not in stream_managers:
                sm = RTSPStreamManager(rtsp_url=rtsp_url, camera_id=cam_id)
                stream_managers[cam_id] = sm
                sm.start()
                print(f"[App] Started stream manager for {cam_id} ({cam_info.get('name')})")
            elif stream_managers[cam_id].rtsp_url != rtsp_url:
                stream_managers[cam_id].save_url(rtsp_url)

            # NVR Recorder
            if cam_id not in nvr_recorders:
                rec = ContinuousNVRRecorder(
                    rtsp_url=rtsp_url,
                    storage_mgr=storage_mgr,
                    segment_duration=seg_duration,
                    quality_profile=quality,
                    camera_id=cam_id,
                    active_filenames_provider=lambda: [r.current_recording_filename for r in nvr_recorders.values() if r and r.current_recording_filename]
                )
                nvr_recorders[cam_id] = rec
                rec.start()
                print(f"[App] Started 24/7 NVR recorder for {cam_id} ({cam_info.get('name')})")
            else:
                rec = nvr_recorders[cam_id]
                if rec.rtsp_url != rtsp_url:
                    rec.restart(rtsp_url)
                if rec.quality_profile != quality:
                    rec.set_quality_profile(quality)


def get_default_camera_id() -> str:
    """Returns the active or first available camera ID."""
    config = load_config()
    active_id = config.get("active_camera")
    cams = config.get("cameras", [])
    if active_id and any(c["id"] == active_id for c in cams):
        return active_id
    if cams:
        return cams[0]["id"]
    return "cam1"


def get_camera_name_map() -> Dict[str, str]:
    """Returns a lookup dict of cam_id -> cam_name."""
    cams = get_cameras()
    return {c["id"]: c.get("name", c["id"]) for c in cams}


def generate_mjpeg(cam_id: str):
    """Generator producing MJPEG frames for a specified camera."""
    encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 80]
    while True:
        sm = stream_managers.get(cam_id)
        if not sm:
            time.sleep(0.1)
            continue

        frame = sm.get_latest_frame()
        ret, buffer = cv2.imencode('.jpg', frame, encode_param)
        if not ret:
            time.sleep(0.03)
            continue

        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n'
               b'Content-Length: ' + str(len(frame_bytes)).encode() + b'\r\n\r\n' +
               frame_bytes + b'\r\n')
        time.sleep(0.02)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/video_feed')
@app.route('/video_feed/<camera_id>')
def video_feed(camera_id: Optional[str] = None):
    if not camera_id:
        camera_id = get_default_camera_id()
    return Response(generate_mjpeg(camera_id), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/api/cameras', methods=['GET', 'POST'])
def api_cameras():
    """Returns list of cameras with live stats or adds a new camera."""
    if request.method == 'GET':
        cams = get_cameras()
        result = []
        for c in cams:
            cam_id = c["id"]
            sm = stream_managers.get(cam_id)
            rec = nvr_recorders.get(cam_id)

            status_info = sm.get_status() if sm else {
                "status": "OFFLINE",
                "fps": 0,
                "width": 0,
                "height": 0
            }

            active_clip = rec.get_active_recording_info() if rec else None

            cam_data = {
                **c,
                "status": status_info.get("status", "OFFLINE"),
                "status_message": status_info.get("status_message", ""),
                "fps": status_info.get("fps", 0),
                "width": status_info.get("width", 0),
                "height": status_info.get("height", 0),
                "active_clip": active_clip,
                "nvr_status": rec.status if rec else "IDLE"
            }
            result.append(cam_data)
        return jsonify({"cameras": result, "default_camera": get_default_camera_id()})

    # POST: Add new camera
    data = request.json or {}
    name = data.get("name", "").strip()
    rtsp_url = data.get("rtsp_url", "").strip()
    image = data.get("image", "/static/mascot_default.jpg")

    if not rtsp_url:
        return jsonify({"success": False, "error": "RTSP URL is required"}), 400

    new_cam = add_camera(name=name, rtsp_url=rtsp_url, image=image)
    sync_camera_services()
    return jsonify({"success": True, "camera": new_cam})


@app.route('/api/cameras/<camera_id>', methods=['GET', 'PUT', 'DELETE'])
def api_camera_detail(camera_id: str):
    """Inspect, update, or remove a camera."""
    cam = get_camera(camera_id)
    if not cam:
        return jsonify({"success": False, "error": f"Camera '{camera_id}' not found"}), 404

    if request.method == 'GET':
        sm = stream_managers.get(camera_id)
        rec = nvr_recorders.get(camera_id)
        status_info = sm.get_status() if sm else {}
        return jsonify({
            **cam,
            "status": status_info.get("status", "OFFLINE"),
            "fps": status_info.get("fps", 0),
            "nvr_status": rec.status if rec else "IDLE"
        })

    if request.method == 'PUT':
        data = request.json or {}
        updated = update_camera(camera_id, data)
        sync_camera_services()
        return jsonify({"success": True, "camera": updated})

    if request.method == 'DELETE':
        success = delete_camera(camera_id)
        sync_camera_services()
        return jsonify({"success": success})


@app.route('/api/status')
@app.route('/api/status/<camera_id>')
def api_status(camera_id: Optional[str] = None):
    """Unified status endpoint for all or a specific camera."""
    if not camera_id:
        camera_id = get_default_camera_id()

    sm = stream_managers.get(camera_id)
    rec = nvr_recorders.get(camera_id)

    status = sm.get_status() if sm else {
        "status": "OFFLINE",
        "status_message": "Stream not running",
        "fps": 0.0,
        "width": 0,
        "height": 0
    }
    status["camera_id"] = camera_id
    status["storage"] = storage_mgr.get_storage_info()
    status["system"] = get_system_metrics()
    status["nvr_status"] = rec.status if rec else "IDLE"
    status["active_clip"] = rec.get_active_recording_info() if rec else None

    # Overview of all cameras for quick header / switcher updates
    cams = get_cameras()
    cam_summary = []
    for c in cams:
        cid = c["id"]
        c_sm = stream_managers.get(cid)
        cam_summary.append({
            "id": cid,
            "name": c.get("name", cid),
            "status": c_sm.status if c_sm else "OFFLINE",
            "fps": c_sm.fps if c_sm else 0.0,
            "image": c.get("image", "/static/mascot_default.jpg")
        })
    status["all_cameras"] = cam_summary
    return jsonify(status)


@app.route('/api/storage')
def api_storage():
    return jsonify(storage_mgr.get_storage_info())


@app.route('/api/system')
def api_system():
    return jsonify(get_system_metrics())


def detect_camera_for_clip(filename: str) -> str:
    """Extracts camera_id from filename or defaults to cam1."""
    # Matches patterns like cam1_20260911_... or cam2_...
    match = re.match(r'^(cam\d+)_', filename)
    if match:
        return match.group(1)
    # Legacy clips (clip_20260830_...) belong to cam1
    return "cam1"


@app.route('/api/clips')
def api_clips():
    """Lists video clips with camera tagging and optional ?camera=<camera_id> filter."""
    cam_filter = request.args.get('camera', 'all').strip()
    name_map = get_camera_name_map()

    clips = []
    video_files = list(RECORDINGS_DIR.glob("*.mp4")) + list(RECORDINGS_DIR.glob("*.mkv"))
    video_files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    # Active recording filenames across all cameras to skip from completed archive
    active_filenames = set()
    active_clips = {}
    for cid, rec in nvr_recorders.items():
        info = rec.get_active_recording_info()
        if info:
            active_clips[cid] = info
            if info.get("filename"):
                active_filenames.add(info["filename"])

    for vf in video_files:
        filename = vf.name
        if filename in active_filenames:
            continue

        size_bytes = vf.stat().st_size
        if size_bytes < 1000:
            continue

        clip_cam_id = detect_camera_for_clip(filename)

        # Apply camera filter if requested
        if cam_filter != 'all' and clip_cam_id != cam_filter:
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
            # Pick any recorder to generate thumbnail
            rec = next(iter(nvr_recorders.values()), None)
            if rec:
                rec._generate_thumbnail(vf, thumb_path)
                has_thumb = thumb_path.exists()

        clips.append({
            "filename": filename,
            "camera_id": clip_cam_id,
            "camera_name": name_map.get(clip_cam_id, clip_cam_id.upper()),
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
        "active_clips": active_clips,
        "storage": storage_mgr.get_storage_info(),
        "camera_filter": cam_filter
    })


@app.route('/api/record/split', methods=['POST'])
def api_record_split():
    """Finalizes active recording into a completed clip."""
    data = request.json or {}
    cam_id = data.get("camera_id") or request.args.get("camera")

    if cam_id and cam_id in nvr_recorders:
        success = nvr_recorders[cam_id].split_segment()
        msg = f"Clip finalized for {cam_id}!"
    else:
        # Split all active recorders
        success = False
        for cid, rec in nvr_recorders.items():
            if rec.split_segment():
                success = True
        msg = "Clips finalized across all cameras!"

    return jsonify({"success": success, "message": msg})


@app.route('/api/clips/<path:filename>')
def serve_video_stream(filename):
    """Serves MP4 video with HTTP 206 Partial Content (Range Requests) support."""
    file_path = RECORDINGS_DIR / filename
    if not file_path.exists() or not file_path.is_file():
        abort(404)

    file_size = file_path.stat().st_size
    range_header = request.headers.get('Range', None)

    if not range_header:
        return send_file(file_path, mimetype='video/mp4')

    byte_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
    if not byte_match:
        return send_file(file_path, mimetype='video/mp4')

    start_byte = int(byte_match.group(1))
    end_byte_str = byte_match.group(2)
    end_byte = int(end_byte_str) if end_byte_str else file_size - 1

    if start_byte >= file_size:
        return Response(status=416)

    length = end_byte - start_byte + 1

    def stream_chunk():
        with open(file_path, 'rb') as f:
            f.seek(start_byte)
            remaining = length
            chunk_size = 64 * 1024
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
    data = request.json or {}
    cam_id = data.get("camera_id") or request.args.get("camera") or get_default_camera_id()
    sm = stream_managers.get(cam_id)
    if not sm:
        return jsonify({"success": False, "error": f"Camera '{cam_id}' not found"}), 404

    try:
        filename = sm.capture_snapshot()
        return jsonify({"success": True, "filename": filename, "url": f"/snapshots/{filename}", "camera_id": cam_id})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/snapshots/<path:filename>')
def serve_snapshot(filename):
    return send_from_directory(SNAPSHOTS_DIR, filename)


@app.route('/api/settings', methods=['GET', 'POST'])
def api_settings():
    if request.method == 'GET':
        config = load_config()
        current_cam_id = get_default_camera_id()
        active_rec = nvr_recorders.get(current_cam_id)
        active_sm = stream_managers.get(current_cam_id)

        return jsonify({
            "config": config,
            "quality_profiles": QUALITY_PROFILES,
            "current_quality": active_rec.quality_profile if active_rec else config.get("quality_profile"),
            "current_storage_limit_gb": round(storage_mgr.max_storage_bytes / (1024 * 1024 * 1024), 1),
            "active_camera": current_cam_id,
            "status": active_sm.get_status() if active_sm else {}
        })

    data = request.json or {}
    config_updates = {}

    # 1. Handle Storage Limit change
    if "storage_limit_gb" in data:
        try:
            new_gb = float(data["storage_limit_gb"])
            if new_gb >= 1.0:
                storage_mgr.set_max_storage_gb(new_gb)
                config_updates["storage_limit_gb"] = new_gb
        except Exception as e:
            print(f"[API Settings] Storage limit error: {e}")

    # 2. Handle Quality Profile change
    if "quality_profile" in data and data["quality_profile"] in QUALITY_PROFILES:
        new_profile = data["quality_profile"]
        for rec in nvr_recorders.values():
            rec.set_quality_profile(new_profile)
        config_updates["quality_profile"] = new_profile

    # 3. Handle Active Camera switch
    if "active_camera" in data:
        config_updates["active_camera"] = data["active_camera"]

    # 4. Handle specific camera settings update
    if "camera_id" in data and "rtsp_url" in data:
        cam_id = data["camera_id"]
        update_camera(cam_id, {"rtsp_url": data["rtsp_url"].strip()})

    # Save to config.json
    if config_updates:
        save_config(config_updates)

    sync_camera_services()

    return jsonify({
        "success": True,
        "config": load_config(),
        "storage": storage_mgr.get_storage_info()
    })


def find_available_port(start_port=5000, max_attempts=10):
    import socket
    for port in range(start_port, start_port + max_attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(('127.0.0.1', port)) != 0:
                return port
    return start_port


if __name__ == '__main__':
    quarantined = storage_mgr.quarantine_corrupted_clips()
    if quarantined:
        print(f"[NVR Startup] Quarantined {len(quarantined)} truncated clip(s) to 'recordings/corrupted': {quarantined}")

    sync_camera_services()

    # Determine base port from CLI argument, env var, or config.json
    configured_port = int(app_config.get("port", 5000))
    if "PORT" in os.environ:
        try:
            configured_port = int(os.environ["PORT"])
        except ValueError:
            pass

    for i, arg in enumerate(sys.argv):
        if arg == "--port" and i + 1 < len(sys.argv):
            try:
                configured_port = int(sys.argv[i + 1])
            except ValueError:
                pass
        elif arg.startswith("--port="):
            try:
                configured_port = int(arg.split("=", 1)[1])
            except ValueError:
                pass

    port = find_available_port(configured_port)
    url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f"  🍓 Raspberry Pi RTSP Multi-Camera NVR & Web Server Active")
    print(f"  Configured Cameras: {len(stream_managers)} online/tracking")
    for cid, sm in stream_managers.items():
        print(f"    - [{cid}] {sm.rtsp_url}")
    print(f"  Max Storage Pool: {storage_mgr.max_storage_bytes / (1024*1024*1024):.1f} GB (15-min segments)")
    print(f"  Open Web UI: {url}")
    print(f"=======================================================\n")

    if "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
    finally:
        print("[App] Stopping all recorders and stream managers...")
        for rec in nvr_recorders.values():
            try:
                rec.stop()
            except Exception:
                pass
        for sm in stream_managers.values():
            try:
                sm.stop()
            except Exception:
                pass
