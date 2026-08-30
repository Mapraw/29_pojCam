import os
import sys
import time
import socket
import subprocess
import threading
import cv2
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from storage_manager import StorageManager, RECORDINGS_DIR, THUMBNAILS_DIR
from motion_detector import MotionDetector

SEGMENT_DURATION_SECONDS = 900  # 15 minutes (900 seconds)

def check_camera_reachable(url: str, timeout: float = 1.5) -> bool:
    """Probes RTSP host and port to verify camera is physically online."""
    try:
        if "@" in url:
            host_part = url.split("@", 1)[1].split("/")[0]
        else:
            host_part = url.replace("rtsp://", "").split("/")[0]

        if ":" in host_part:
            host, port_str = host_part.split(":", 1)
            port = int(port_str)
        else:
            host = host_part
            port = 554

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        res = s.connect_ex((host, port))
        try:
            s.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
        s.close()
        return res == 0
    except Exception:
        return False


class ContinuousNVRRecorder:
    def __init__(self, rtsp_url: str, storage_mgr: StorageManager, segment_duration: int = SEGMENT_DURATION_SECONDS, quality_profile: str = "480p_10fps"):
        self.rtsp_url = rtsp_url
        self.storage_mgr = storage_mgr
        self.segment_duration = segment_duration
        self.quality_profile = quality_profile
        self.motion_detector = MotionDetector()

        self.is_running = False
        self.ffmpeg_proc: Optional[subprocess.Popen] = None
        self.recorder_thread: Optional[threading.Thread] = None
        self.watcher_thread: Optional[threading.Thread] = None
        self.stop_event = threading.Event()
        self.split_requested = threading.Event()

        self.status = "IDLE"  # IDLE, RECORDING, RECONNECTING, OFFLINE
        self.status_message = "Recorder initialized"
        
        # Explicit active recording state
        self.current_recording_filename: Optional[str] = None
        self.segment_start_time: float = time.time()
        self.proc_lock = threading.Lock()

    def set_quality_profile(self, new_profile: str):
        """Updates the video recording quality profile (e.g. 480p_10fps, 720p_native, 1080p_full)."""
        if self.quality_profile != new_profile:
            print(f"[NVR Recorder] Switching quality profile: {self.quality_profile} -> {new_profile}")
            self.quality_profile = new_profile
            if self.is_running:
                self.restart()

    def start(self):
        """Starts the background continuous 15-minute chunk recording."""
        if self.is_running:
            return
        self.is_running = True
        self.stop_event.clear()
        self.split_requested.clear()
        
        self.recorder_thread = threading.Thread(target=self._recording_loop, daemon=True)
        self.recorder_thread.start()

        self.watcher_thread = threading.Thread(target=self._storage_and_thumbnail_watcher, daemon=True)
        self.watcher_thread.start()

    def stop(self):
        """Gracefully stops the continuous recording process."""
        self.is_running = False
        self.stop_event.set()
        
        with self.proc_lock:
            if self.ffmpeg_proc is not None:
                try:
                    if self.ffmpeg_proc.stdin and not self.ffmpeg_proc.stdin.closed:
                        self.ffmpeg_proc.stdin.write(b"q\r\n")
                        self.ffmpeg_proc.stdin.flush()
                        self.ffmpeg_proc.stdin.close()
                    self.ffmpeg_proc.wait(timeout=10)
                except Exception:
                    try:
                        self.ffmpeg_proc.kill()
                        self.ffmpeg_proc.wait(timeout=2)
                    except Exception:
                        pass
                self.ffmpeg_proc = None

        self.status = "IDLE"
        self.status_message = "Recorder stopped"
        self.current_recording_filename = None

    def split_segment(self) -> bool:
        """Finalizes the currently active recording segment immediately and starts a new segment."""
        if self.is_running:
            self.split_requested.set()
            with self.proc_lock:
                proc = self.ffmpeg_proc
                if proc is not None and proc.poll() is None:
                    print("[NVR Recorder] Finalize requested. Sending graceful 'q' signal to complete current clip...")
                    try:
                        if proc.stdin and not proc.stdin.closed:
                            proc.stdin.write(b"q\r\n")
                            proc.stdin.flush()
                            proc.stdin.close()
                    except Exception:
                        pass
                    return True
        return False

    def restart(self, new_url: Optional[str] = None):
        """Restarts recorder with same or updated RTSP URL."""
        if new_url:
            self.rtsp_url = new_url
        self.stop()
        time.sleep(0.5)
        self.start()

    def get_active_recording_info(self) -> Optional[Dict[str, Any]]:
        """Returns details of the segment currently being recorded."""
        if self.status != "RECORDING" or not self.current_recording_filename:
            return None
        
        filepath = RECORDINGS_DIR / self.current_recording_filename
        size_bytes = filepath.stat().st_size if filepath.exists() else 0
        elapsed = int(max(0, time.time() - (self.segment_start_time or time.time())))
        
        return {
            "filename": self.current_recording_filename,
            "size_mb": round(size_bytes / (1024 * 1024), 2),
            "elapsed_seconds": elapsed,
            "elapsed_formatted": f"{elapsed//60:02d}:{elapsed%60:02d}",
            "quality_profile": self.quality_profile,
            "is_recording": True
        }

    def _build_ffmpeg_cmd(self, output_filename: str) -> list:
        """
        Builds FFmpeg command with native -t duration for automatic 15-minute segmentation,
        10-second resilient network timeout, and audio resampling for rock-solid NVR reliability.
        """
        output_path = str(RECORDINGS_DIR / output_filename)
        input_url = self.rtsp_url
        duration_str = str(int(self.segment_duration))

        if self.quality_profile == "480p_10fps":
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "10000000",             # 10-second socket timeout
                "-fflags", "+genpts+discardcorrupt",
                "-i", input_url,
                "-t", duration_str,
                "-vf", "scale=854:480,fps=10",
                "-g", "20",                          # Force keyframe every 2 seconds
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-b:v", "220k",
                "-maxrate", "280k",
                "-bufsize", "500k",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "32k",
                "-ar", "16000",
                "-af", "aresample=async=1",
                "-movflags", "+faststart",
                "-y", output_path
            ]
        elif self.quality_profile == "360p_10fps":
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "10000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", input_url,
                "-t", duration_str,
                "-vf", "scale=640:360,fps=10",
                "-g", "20",
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-b:v", "150k",
                "-maxrate", "200k",
                "-bufsize", "400k",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "32k",
                "-ar", "16000",
                "-af", "aresample=async=1",
                "-movflags", "+faststart",
                "-y", output_path
            ]
        elif self.quality_profile == "720p_native":
            sub_url = input_url.replace("/stream1", "/stream2")
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "10000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", sub_url,
                "-t", duration_str,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "64k",
                "-ar", "16000",
                "-af", "aresample=async=1",
                "-movflags", "+faststart",
                "-y", output_path
            ]
        else:  # 1080p_full
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "10000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", input_url,
                "-t", duration_str,
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "64k",
                "-ar", "16000",
                "-af", "aresample=async=1",
                "-movflags", "+faststart",
                "-y", output_path
            ]

        return cmd

    def _recording_loop(self):
        """
        Supervisor loop that records consecutive 15-minute segments 24/7.
        - Automatically cuts and saves cleanly at 15 minutes via FFmpeg native -t.
        - Gracefully finalizes when the camera unplugs, turns off, or on manual split.
        - Seamlessly rolls over to subsequent clips with camera session cooldown.
        """
        last_segment_success = False

        while not self.stop_event.is_set():
            # 1. Proactive Probe: Only probe socket if recovering from an offline state/error
            if not last_segment_success:
                if not check_camera_reachable(self.rtsp_url, timeout=2.0):
                    self.status = "OFFLINE"
                    self.status_message = "Camera offline / unplugged. Waiting for camera to boot..."
                    self.current_recording_filename = None
                    time.sleep(2.5)
                    continue

            # 2. Generate new timestamped filename for this specific 15-min segment
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"clip_{timestamp}.mp4"
            self.current_recording_filename = output_filename
            self.segment_start_time = time.time()
            self.split_requested.clear()

            cmd = self._build_ffmpeg_cmd(output_filename)
            self.status = "RECORDING"
            self.status_message = f"Recording {output_filename} ({self.quality_profile})"
            print(f"[NVR Recorder] Starting new {self.quality_profile} segment: {output_filename} ({self.segment_duration}s target)...")

            proc = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                with self.proc_lock:
                    self.ffmpeg_proc = proc

                # 3. Active Supervisor Loop
                while not self.stop_event.is_set():
                    poll_code = proc.poll()
                    if poll_code is not None:
                        print(f"[NVR Recorder] FFmpeg process completed on {output_filename} (exit code {poll_code}).")
                        break

                    # Check if early split was requested (e.g. user clicked "Finalize Clip Now")
                    if self.split_requested.is_set():
                        print(f"[NVR Recorder] Split requested on {output_filename}. Sending graceful quit...")
                        try:
                            if proc.stdin and not proc.stdin.closed:
                                proc.stdin.write(b"q\r\n")
                                proc.stdin.flush()
                                proc.stdin.close()
                        except Exception:
                            pass
                        break

                    time.sleep(1.0)

            except Exception as e:
                print(f"[NVR Recorder] Error running FFmpeg on {output_filename}: {e}")

            # Ensure clean wait for FFmpeg to finalize file and write faststart moov atom
            if proc is not None:
                try:
                    if proc.poll() is None:
                        try:
                            if proc.stdin and not proc.stdin.closed:
                                proc.stdin.write(b"q\r\n")
                                proc.stdin.flush()
                                proc.stdin.close()
                        except Exception:
                            pass
                        proc.wait(timeout=15)
                except Exception:
                    try:
                        print(f"[NVR Recorder] Warning: FFmpeg wait timeout exceeded on {output_filename}. Forcing terminate...")
                        proc.kill()
                        proc.wait(timeout=3)
                    except Exception:
                        pass

            with self.proc_lock:
                self.ffmpeg_proc = None

            # Small delay to let filesystem write finalize
            time.sleep(0.3)

            # Generate thumbnail or cleanup if empty stub
            completed_file = RECORDINGS_DIR / output_filename
            if completed_file.exists():
                file_size = completed_file.stat().st_size
                if file_size > 2000:
                    last_segment_success = True
                    thumb_file = THUMBNAILS_DIR / f"{completed_file.stem}.jpg"
                    self._generate_thumbnail(completed_file, thumb_file)
                    print(f"[NVR Recorder] Successfully saved clip {output_filename} ({file_size / (1024*1024):.2f} MB).")
                    
                    # 1.5s camera session cooldown before starting the next consecutive clip
                    if not self.stop_event.is_set():
                        self.status = "RECORDING"
                        time.sleep(1.5)
                else:
                    last_segment_success = False
                    try:
                        completed_file.unlink(missing_ok=True)
                    except Exception:
                        pass
                    if not self.stop_event.is_set():
                        self.status = "RECONNECTING"
                        time.sleep(2.5)
            else:
                last_segment_success = False
                if not self.stop_event.is_set():
                    self.status = "RECONNECTING"
                    time.sleep(2.5)

    def _storage_and_thumbnail_watcher(self):
        """
        Background maintenance thread:
        1. Generates thumbnails for any completed MP4 clips.
        2. Enforces the storage cap.
        """
        while not self.stop_event.is_set():
            try:
                # 1. Generate thumbnails for completed video clips
                video_clips = list(RECORDINGS_DIR.glob("*.mp4"))
                active_name = self.current_recording_filename

                for clip in video_clips:
                    if active_name and clip.name == active_name:
                        continue

                    thumb_path = THUMBNAILS_DIR / f"{clip.stem}.jpg"
                    if not thumb_path.exists() and clip.stat().st_size > 2000:
                        self._generate_thumbnail(clip, thumb_path)

                # 2. Enforce storage limit (safely skipping the currently active recording)
                freed, deleted = self.storage_mgr.cleanup_if_needed(active_filename=self.current_recording_filename)
                if deleted:
                    print(f"[NVR Recorder] Storage cleanup freed {freed / (1024*1024):.1f} MB ({len(deleted)} clips).")

            except Exception as e:
                print(f"[NVR Recorder] Watcher error: {e}")

            time.sleep(10.0)

    def _generate_thumbnail(self, video_path: Path, thumb_path: Path) -> bool:
        """
        Robust thumbnail extractor with OpenCV primary engine and FFmpeg CLI fallback.
        Guarantees thumbnail is generated for all valid clips.
        """
        if not video_path.exists() or video_path.stat().st_size < 1000:
            return False

        # Attempt 1: OpenCV direct frame capture
        try:
            cap = cv2.VideoCapture(str(video_path))
            if cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    for _ in range(10):
                        ret, frame = cap.read()
                        if ret and frame is not None:
                            break

                cap.release()

                if ret and frame is not None:
                    thumb = cv2.resize(frame, (400, 225), interpolation=cv2.INTER_AREA)
                    cv2.imwrite(str(thumb_path), thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                    return True
        except Exception as e:
            print(f"[NVR Recorder] OpenCV thumbnail read error for {video_path.name}: {e}")

        # Attempt 2: FFmpeg CLI fallback
        try:
            thumb_cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "quiet",
                "-ss", "00:00:00.500",
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", "scale=400:225",
                "-q:v", "3",
                "-y", str(thumb_path)
            ]
            res = subprocess.run(thumb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=6)
            if thumb_path.exists() and thumb_path.stat().st_size > 500:
                return True
        except Exception as e:
            print(f"[NVR Recorder] FFmpeg fallback thumbnail error for {video_path.name}: {e}")

        return False
