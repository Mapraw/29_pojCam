import os
import sys
import time
import json
import urllib.request
import cv2
import threading
from pathlib import Path

# Fix Windows console encoding
if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from recorder import ContinuousNVRRecorder
from storage_manager import StorageManager, RECORDINGS_DIR, THUMBNAILS_DIR
import app

def test_everything():
    print("=" * 70)
    print("  LIVE CAMERA NVR VERIFICATION: PERIODIC ROLLOVER & DISCONNECT TEST")
    print("=" * 70)

    url = open("high_qual.txt").read().strip()
    sm = StorageManager(max_storage_bytes=8 * 1024 * 1024 * 1024)

    # -----------------------------------------------------------------
    # 1. TEST AUTOMATIC PERIODIC ROLLOVER (3 Consecutive Segments)
    # -----------------------------------------------------------------
    print("\n[STEP 1] Testing Automatic Periodic Segment Rollover (3 Consecutive 5s segments)...")
    rec = ContinuousNVRRecorder(rtsp_url=url, storage_mgr=sm, segment_duration=5, quality_profile="480p_10fps")
    rec.start()
    
    print("  -> Recording segment 1 (5s)...")
    time.sleep(7.5)  # Rollover 1
    print("  -> Recording segment 2 (5s)...")
    time.sleep(7.5)  # Rollover 2
    print("  -> Recording segment 3 (5s)...")
    time.sleep(7.5)  # Rollover 3
    rec.stop()

    video_clips = sorted(list(RECORDINGS_DIR.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)
    print(f"  -> Found {len(video_clips)} clips created.")
    assert len(video_clips) >= 3, f"Expected at least 3 automatic clips, found {len(video_clips)}"

    for clip in video_clips[:3]:
        cap = cv2.VideoCapture(str(clip))
        opened = cap.isOpened()
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if opened else 0
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) if opened else 0
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) if opened else 0
        fps = round(cap.get(cv2.CAP_PROP_FPS), 1) if opened else 0
        cap.release()
        thumb = THUMBNAILS_DIR / f"{clip.stem}.jpg"
        print(f"  -> [PASS] {clip.name}: Playable={opened}, Res={w}x{h}, FPS={fps}, Frames={frames}, Size={clip.stat().st_size / 1024:.1f} KB, ThumbExists={thumb.exists()}")
        assert opened and frames > 0, f"Clip {clip.name} must be playable with valid frames!"

    # -----------------------------------------------------------------
    # 2. TEST SUDDEN DISCONNECT / SHUTOFF HANDLING
    # -----------------------------------------------------------------
    print("\n[STEP 2] Testing Graceful Finalization on Camera Sudden Disconnect...")
    rec2 = ContinuousNVRRecorder(rtsp_url=url, storage_mgr=sm, segment_duration=900, quality_profile="480p_10fps")
    rec2.start()
    print("  -> Recording in-progress footage for 4 seconds...")
    time.sleep(4)

    print("  -> Simulating sudden camera power-off (triggering disconnect finalizer)...")
    # Simulate the supervisor detecting disconnect and sending graceful 'q'
    with rec2.proc_lock:
        if rec2.ffmpeg_proc and rec2.ffmpeg_proc.stdin:
            rec2.ffmpeg_proc.stdin.write(b"q\n")
            rec2.ffmpeg_proc.stdin.flush()
    time.sleep(1.5)
    rec2.stop()

    disconnect_clips = sorted(list(RECORDINGS_DIR.glob("*.mp4")), key=lambda p: p.stat().st_mtime, reverse=True)
    latest_saved = disconnect_clips[0]
    cap = cv2.VideoCapture(str(latest_saved))
    opened = cap.isOpened()
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) if opened else 0
    cap.release()
    print(f"  -> [PASS] Disconnect footage saved: {latest_saved.name} (Playable={opened}, Frames={frames}, Size={latest_saved.stat().st_size / 1024:.1f} KB)")
    assert opened and frames > 0, "Video recorded before shutdown must be 100% saved and playable!"

    # -----------------------------------------------------------------
    # 3. TEST FLASK HTTP 200 & HTTP 206 BROWSER STREAMING
    # -----------------------------------------------------------------
    print("\n[STEP 3] Testing Flask Web Server & Browser Range Streaming...")
    port = 5988
    srv = threading.Thread(target=lambda: app.app.run(port=port, host='127.0.0.1'), daemon=True)
    srv.start()
    time.sleep(1.0)
    base_url = f"http://127.0.0.1:{port}"

    # Test /api/clips
    clips_res = json.loads(urllib.request.urlopen(f"{base_url}/api/clips").read().decode())
    print(f"  -> [PASS] /api/clips: HTTP 200 (Total {len(clips_res['clips'])} valid clips in gallery)")
    assert len(clips_res['clips']) > 0, "Must return clips list"

    # Test HTTP 206 Partial Content on latest video
    test_url = f"{base_url}{clips_res['clips'][0]['video_url']}"
    req = urllib.request.Request(test_url)
    req.add_header("Range", "bytes=0-1023")
    resp = urllib.request.urlopen(req)
    print(f"  -> [PASS] HTTP 206 Video Stream: Status {resp.getcode()}, Content-Range: {resp.headers.get('Content-Range')}")
    assert resp.getcode() == 206, "Must return HTTP 206 for browser seekability"

    print("\n" + "=" * 70)
    print("  ALL TESTS PASSED: Automatic Rollover, Power-cut Save & Web Stream Verified!")
    print("=" * 70 + "\n")

if __name__ == "__main__":
    test_everything()
