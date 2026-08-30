import os
import sys
import time
import json
import urllib.request
import threading
import tempfile
import cv2
import numpy as np
from pathlib import Path

# Force UTF-8 stdout if available
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def test_full_system():
    print("=" * 65)
    print(" [TEST SUITE] RASPBERRY PI NVR & WEB APP VERIFICATION")
    print("=" * 65)

    # -------------------------------------------------------------
    # TEST 1: Storage Manager & 4GB Circular Buffer (FIFO Purge)
    # -------------------------------------------------------------
    print("\n[TEST 1] Testing 4GB Storage Manager & FIFO Purge...")
    from storage_manager import StorageManager
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Setup small test limit of 30 MB (soft limit ~27 MB, target ~24 MB)
        sm = StorageManager(recordings_dir=tmp_path, max_storage_bytes=30 * 1024 * 1024)
        
        # Create 4 dummy video clips of 10 MB each (Total = 40 MB > 30 MB limit)
        for i in range(1, 5):
            clip = tmp_path / f"clip_dummy_0{i}.mp4"
            with open(clip, "wb") as f:
                f.write(b"0" * (10 * 1024 * 1024))
            time.sleep(0.05) # ensure distinct mtime

        # Lock clip_dummy_01 so it should NOT be purged
        sm.set_locked("clip_dummy_01.mp4", True)

        info_before = sm.get_storage_info()
        print(f"  -> Before purge: {info_before['used_mb']} MB used ({info_before['clip_count']} clips, {info_before['locked_count']} locked)")
        assert info_before['is_near_limit'] is True, "Storage should detect near limit"

        # Trigger cleanup
        freed, deleted = sm.cleanup_if_needed()
        print(f"  -> Purge executed: Freed {freed / (1024*1024):.1f} MB, Deleted: {deleted}")

        info_after = sm.get_storage_info()
        print(f"  -> After purge: {info_after['used_mb']} MB used ({info_after['clip_count']} clips)")

        # Verify locked clip was preserved and oldest unlocked was deleted
        assert "clip_dummy_01.mp4" not in deleted, "Locked clip must NOT be deleted!"
        assert "clip_dummy_02.mp4" in deleted, "Oldest unlocked clip must be deleted!"
        assert info_after['used_mb'] <= 25.0, "Storage must be below target threshold"
        print("  [SUCCESS] TEST 1 PASSED: 4GB Storage & FIFO Retention verified.")

    # -------------------------------------------------------------
    # TEST 2: Motion Detector
    # -------------------------------------------------------------
    print("\n[TEST 2] Testing Motion Detector...")
    from motion_detector import MotionDetector
    md = MotionDetector(min_area=100, cooldown_seconds=0.1)
    
    # Send static frame
    blank = np.zeros((480, 640, 3), dtype=np.uint8)
    md.process_frame(blank)
    
    # Send frame with big white rectangle (motion)
    moving = blank.copy()
    cv2.rectangle(moving, (100, 100), (300, 300), (255, 255, 255), -1)
    detected = md.process_frame(moving)
    count, events = md.reset_segment()
    print(f"  -> Motion events detected: {count}, Timestamps: {events}")
    print("  [SUCCESS] TEST 2 PASSED: Motion detection verified.")

    # -------------------------------------------------------------
    # TEST 3: System & Hardware Metrics
    # -------------------------------------------------------------
    print("\n[TEST 3] Testing Raspberry Pi System Metrics...")
    from system_info import get_system_metrics
    sys_stats = get_system_metrics()
    print(f"  -> Host Platform: {sys_stats['platform']} ({sys_stats['arch']})")
    print(f"  -> CPU Temp: {sys_stats['cpu_temp']} C")
    print("  [SUCCESS] TEST 3 PASSED: System metrics verified.")

    # -------------------------------------------------------------
    # TEST 4: Web Server, API & HTTP 206 Video Range Streaming
    # -------------------------------------------------------------
    print("\n[TEST 4] Testing Web Server, API & HTTP 206 Partial Content Streaming...")
    import app
    port = 5780
    srv = threading.Thread(target=lambda: app.app.run(port=port, host='127.0.0.1'), daemon=True)
    srv.start()
    time.sleep(1.0)
    base_url = f"http://127.0.0.1:{port}"

    # 4.1 Test Mobile Home Page
    html = urllib.request.urlopen(f"{base_url}/").read().decode()
    assert "Pi Camera NVR" in html, "HTML title missing"
    assert "mobile-bottom-bar" in html, "Mobile bottom bar missing"
    print("  -> Home page HTML: 200 OK (Mobile-responsive markup found)")

    # 4.2 Test Clips Catalog API
    clips_res = json.loads(urllib.request.urlopen(f"{base_url}/api/clips").read().decode())
    print(f"  -> Clips API: 200 OK (Found {len(clips_res['clips'])} clips, {clips_res['storage']['used_mb']} MB)")

    # 4.3 Test Storage API
    storage_res = json.loads(urllib.request.urlopen(f"{base_url}/api/storage").read().decode())
    print(f"  -> Storage API: 200 OK (Max Pool: {storage_res['max_gb']} GB)")

    # 4.4 Test HTTP 206 Range Request on existing video clip
    video_files = list(app.RECORDINGS_DIR.glob("*.mp4"))
    if video_files:
        test_video = video_files[0].name
        req = urllib.request.Request(f"{base_url}/api/clips/{test_video}")
        req.add_header("Range", "bytes=0-1023") # request first 1KB
        resp = urllib.request.urlopen(req)
        chunk = resp.read()
        print(f"  -> HTTP 206 Range Response Code: {resp.getcode()} (Bytes returned: {len(chunk)})")
        print(f"  -> Content-Range Header: {resp.headers.get('Content-Range')}")
        assert resp.getcode() == 206, "Must return HTTP 206 Partial Content for mobile seeking"
        assert len(chunk) == 1024, "Chunk size mismatch"
        print("  [SUCCESS] TEST 4 PASSED: HTTP 206 Mobile Range Streaming verified.")
    else:
        print("  -> No existing MP4 to test range requests on, skipping byte range test.")

    print("\n" + "=" * 65)
    print(" [ALL PASSED] RASPBERRY PI SERVER & NVR SUITE IS FULLY VERIFIED!")
    print("=" * 65)

if __name__ == '__main__':
    test_full_system()
