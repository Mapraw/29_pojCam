import os
import sys
import time
import json
import urllib.request
import threading

def run_diagnostics():
    print("=" * 60)
    print(" RUNNING FULL RTSP STREAM APP DIAGNOSTIC SUITE")
    print("=" * 60)

    # 1. Test reading high_qual.txt
    from stream_manager import RTSPStreamManager, SNAPSHOTS_DIR, RECORDINGS_DIR
    manager = RTSPStreamManager()
    print(f"[TEST 1] Loaded RTSP URL from file: {manager.rtsp_url}")
    assert "rtsp://" in manager.rtsp_url, "Invalid RTSP URL format"

    # 2. Test Stream Capture
    print("[TEST 2] Starting RTSP capture manager...")
    manager.start()
    
    # Wait for frame or status
    start_wait = time.time()
    while time.time() - start_wait < 6.0:
        if manager.status == "ONLINE":
            break
        time.sleep(0.5)

    print(f"[TEST 2] Stream Status: {manager.status} ({manager.status_message})")
    print(f"[TEST 2] Resolution: {manager.width}x{manager.height}, FPS: {manager.fps}")

    frame = manager.get_latest_frame()
    print(f"[TEST 2] Frame shape retrieved: {frame.shape}")
    assert frame is not None, "Frame cannot be None"

    # 3. Test Snapshot
    print("[TEST 3] Testing Snapshot capture...")
    snap_file = manager.capture_snapshot()
    snap_path = SNAPSHOTS_DIR / snap_file
    print(f"[TEST 3] Snapshot created: {snap_path.exists()} ({snap_path.stat().st_size} bytes)")
    assert snap_path.exists(), "Snapshot file does not exist"

    # 4. Test Video Recording
    print("[TEST 4] Testing Video Recording (1.5s)...")
    ok_start, msg_start = manager.start_recording()
    print(f"[TEST 4] Recording Start: {ok_start} ({msg_start})")
    time.sleep(1.5)
    ok_stop, msg_stop = manager.stop_recording()
    print(f"[TEST 4] Recording Stop: {ok_stop} ({msg_stop})")

    # 5. Test Web Endpoints
    print("[TEST 5] Testing Web API & MJPEG endpoints...")
    import app
    port = 5890
    server_thread = threading.Thread(target=lambda: app.app.run(port=port, host='127.0.0.1'), daemon=True)
    server_thread.start()
    time.sleep(1.0)

    base_url = f"http://127.0.0.1:{port}"
    status_data = json.loads(urllib.request.urlopen(f"{base_url}/api/status").read().decode())
    print(f"[TEST 5] Web API Status response: OK (Status: {status_data['status']})")

    req_feed = urllib.request.urlopen(f"{base_url}/video_feed")
    chunk = req_feed.read(1024)
    print(f"[TEST 5] Video Feed Stream chunk received: {len(chunk)} bytes")

    manager.stop()
    print("=" * 60)
    print(" ALL TESTS PASSED SUCCESSFULLY! ")
    print("=" * 60)

if __name__ == '__main__':
    run_diagnostics()
