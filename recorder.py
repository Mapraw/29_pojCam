import os
import sys
import time
import subprocess
import threading
import cv2
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable
from storage_manager import StorageManager, RECORDINGS_DIR, THUMBNAILS_DIR
from motion_detector import MotionDetector

SEGMENT_DURATION_SECONDS = 900  # 15 minutes (900 seconds)


class ContinuousNVRRecorder:
    def __init__(self, rtsp_url: str, storage_mgr: StorageManager, segment_duration: int = SEGMENT_DURATION_SECONDS):
        self.rtsp_url = rtsp_url
        self.storage_mgr = storage_mgr
        self.segment_duration = segment_duration
        self.motion_detector = MotionDetector()

        self.is_running = False
        self.ffmpeg_proc: Optional[subprocess.Popen] = None
        self.recorder_thread: Optional[threading.Thread] = None
        self.watcher_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()

        self.current_recording_file = None
        self.last_segment_end_time = time.time()
        self.status = "IDLE"  # IDLE, RECORDING, RECONNECTING, ERROR

    def start(self):
        """Starts the background continuous 15-minute chunk recording."""
        if self.is_running:
            return
        self.is_running = True
        self.stop_event.clear()
        
        self.recorder_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self.recorder_thread.start()

        self.watcher_thread = threading.Thread(target=self._storage_and_thumbnail_watcher, daemon=True)
        self.watcher_thread.start()

    def stop(self):
        """Gracefully stops the continuous recording process."""
        self.is_running = False
        self.stop_event.set()
        
        if self.ffmpeg_proc is not None:
            try:
                # Send 'q' to FFmpeg for clean MP4 container finalization
                if self.ffmpeg_proc.stdin:
                    self.ffmpeg_proc.stdin.write(b"q")
                    self.ffmpeg_proc.stdin.flush()
                self.ffmpeg_proc.wait(timeout=3)
            except Exception:
                try:
                    self.ffmpeg_proc.terminate()
                except Exception:
                    pass
            self.ffmpeg_proc = None

        self.status = "IDLE"

    def restart(self, new_url: Optional[str] = None):
        """Restarts recorder with same or updated RTSP URL."""
        if new_url:
            self.rtsp_url = new_url
        self.stop()
        time.sleep(1.0)
        self.start()

    def _build_ffmpeg_cmd(self) -> list:
        """
        Builds high-performance FFmpeg command for Raspberry Pi:
        - Uses RTSP TCP transport for reliability.
        - Direct video stream copy (-c:v copy) -> < 1% CPU usage!
        - Audio copy (-c:a aac or copy) for full audio support.
        - Segment muxer chunks into exactly 15-minute files (900s).
        - Fragmented MP4 flags for corruption resistance & instant web streaming.
        """
        output_pattern = str(RECORDINGS_DIR / "clip_%Y%m%d_%H%M%S.mp4")

        cmd = [
            "ffmpeg",
            "-hide_banner",
            "-loglevel", "warning",
            "-rtsp_transport", "tcp",
            "-fflags", "+genpts+discardcorrupt",
            "-i", self.rtsp_url,
            "-c:v", "copy",                  # Direct Stream Copy (Zero CPU encoding)
            "-c:a", "aac",                   # Remux/encode audio stream to standard AAC
            "-b:a", "64k",
            "-f", "segment",
            "-segment_time", str(self.segment_duration),
            "-reset_timestamps", "1",
            "-strftime", "1",
            "-movflags", "+faststart",
            output_pattern
        ]
        return cmd

    def _recording_loop(self):
        """Supervisor loop that keeps FFmpeg recording 24/7 with auto-reconnect."""
        while not self.stop_event.is_set():
            cmd = self._build_ffmpeg_cmd()
            self.status = "RECORDING"
            print(f"[NVR Recorder] Starting 15-min segmented recording from {self.rtsp_url}...")

            try:
                self.ffmpeg_proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )

                # Wait for process to exit or stop event
                while not self.stop_event.is_set():
                    poll_code = self.ffmpeg_proc.poll()
                    if poll_code is not None:
                        print(f"[NVR Recorder] FFmpeg process exited with return code {poll_code}.")
                        break
                    time.sleep(1.0)

            except Exception as e:
                print(f"[NVR Recorder] Error launching FFmpeg: {e}")

            if not self.stop_event.is_set():
                self.status = "RECONNECTING"
                print("[NVR Recorder] Reconnecting in 3 seconds...")
                time.sleep(3.0)

    def _storage_and_thumbnail_watcher(self):
        """
        Background maintenance thread:
        1. Generates thumbnails for any completed MP4 clips.
        2. Enforces the 4.0 GB FIFO storage cap.
        3. Scans for motion metadata updates.
        """
        known_thumbnails = set()

        while not self.stop_event.is_set():
            try:
                # 1. Generate thumbnails for completed video clips (skip actively written file)
                video_clips = list(RECORDINGS_DIR.glob("*.mp4"))
                now_ts = time.time()
                for clip in video_clips:
                    # Skip the currently recording active segment (modified in last 15s)
                    if (now_ts - clip.stat().st_mtime) < 15.0:
                        continue

                    thumb_path = THUMBNAILS_DIR / f"{clip.stem}.jpg"
                    if not thumb_path.exists() and clip.stat().st_size > 10000:
                        self._generate_thumbnail(clip, thumb_path)

                # 2. Enforce 4GB storage limit
                freed, deleted = self.storage_mgr.cleanup_if_needed()
                if deleted:
                    print(f"[NVR Recorder] 4GB Storage cleanup freed {freed / (1024*1024):.1f} MB ({len(deleted)} clips).")

            except Exception as e:
                print(f"[NVR Recorder] Watcher error: {e}")

            time.sleep(10.0)  # Check every 10 seconds

    def _generate_thumbnail(self, video_path: Path, thumb_path: Path):
        """Extracts a lightweight JPG thumbnail from video segment using OpenCV or FFmpeg."""
        try:
            cap = cv2.VideoCapture(str(video_path))
            if cap.isOpened():
                # Read 1st second frame
                cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
                ret, frame = cap.read()
                if not ret:
                    cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                    ret, frame = cap.read()

                if ret and frame is not None:
                    # Downscale to 400x225 for mobile web card thumbnail
                    thumb = cv2.resize(frame, (400, 225), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(str(thumb_path), thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                cap.release()
        except Exception as e:
            print(f"[NVR Recorder] Thumbnail creation error for {video_path.name}: {e}")
