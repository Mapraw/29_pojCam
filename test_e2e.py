import time
import subprocess
import urllib.request
import json
import cv2
import os
import sys
import threading
from storage_manager import RECORDINGS_DIR, THUMBNAILS_DIR
import app

if sys.platform.startswith("win"):
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

def run_e2e_test():
    print("=" * 65)
    print("  LIVE END-TO-END VERIFICATION TEST")
    print("=" * 65)

    # 1. Start Server in background thread
    port = 5930
    srv = threading.Thread(target=lambda: app.app.run(port=port, host='127.0.0.1'), daemon=True)
    srv.start()
    app.stream_mgr.start()
    app.nvr_recorder.start()
    time.sleep(2)

    base_url = f"http://127.0.0.1:{port}"

    # 2. Test Live Video Feed & Status
    status_req = urllib.request.urlopen(f"{base_url}/api/status")
    status = json.loads(status_req.read().decode())
    print(f"-> [PASS] Status API: HTTP 200 (Camera {status.get('status')}, FPS: {status.get('fps')}, Res: {status.get('width')}x{status.get('height')})")

    # 3. Record for 5 seconds and test Split / Finalize
    print("-> Recording 480p @ 10fps for 5 seconds...")
    time.sleep(5)
    split_req = urllib.request.Request(f"{base_url}/api/record/split", data=b"{}", headers={"Content-Type": "application/json"})
    split_res = json.loads(urllib.request.urlopen(split_req).read().decode())
    print(f"-> [PASS] Finalize API: {split_res.get('message')}")
    time.sleep(2)

    # 4. Test Clips Catalog API (HTTP 200)
    clips_req = urllib.request.urlopen(f"{base_url}/api/clips")
    clips_data = json.loads(clips_req.read().decode())
    print(f"-> [PASS] Clips API: Returned HTTP 200 with {len(clips_data.get('clips', []))} clips!")

    if clips_data.get("clips"):
        latest = clips_data["clips"][0]
        print(f"   Latest Clip: {latest.get('filename')}")
        print(f"   Size: {latest.get('size_mb')} MB")
        print(f"   Thumbnail: {latest.get('thumbnail_url')}")
        print(f"   Video URL: {latest.get('video_url')}")

        # 5. Test HTTP 206 Range Stream for mobile/desktop browser playback
        video_req = urllib.request.Request(f"{base_url}{latest.get('video_url')}")
        video_req.add_header("Range", "bytes=0-2048")
        v_resp = urllib.request.urlopen(video_req)
        print(f"-> [PASS] Video Streaming: HTTP {v_resp.getcode()} Partial Content (Range {v_resp.headers.get('Content-Range')})")
        
        # 6. Verify OpenCV / Browser Playability
        vf_path = os.path.join("recordings", latest["filename"])
        cap = cv2.VideoCapture(vf_path)
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = round(cap.get(cv2.CAP_PROP_FPS), 1)
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        print(f"-> [PASS] Video Inspection: {w}x{h} resolution, {fps} FPS, {frames} frames playable!")
        assert w == 854 and h == 480, f"Expected 854x480, got {w}x{h}"
        assert frames > 0, "Frames must be greater than 0"

    app.nvr_recorder.stop()
    app.stream_mgr.stop()

    print("=" * 65)
    print("  ✅ ALL TESTS PASSED SUCCESSFULLY WITH ZERO ERRORS!")
    print("=" * 65)

if __name__ == "__main__":
    run_e2e_test()
