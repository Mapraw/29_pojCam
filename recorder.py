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

def check_camera_reachable(url: str, timeout: float = 2.0) -> bool:
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
                    if self.ffmpeg_proc.stdin:
                        self.ffmpeg_proc.stdin.write(b"q")
                        self.ffmpeg_proc.stdin.flush()
                    self.ffmpeg_proc.wait(timeout=3)
                except Exception:
                    try:
                        self.ffmpeg_proc.kill()
                    except Exception:
                        pass
                self.ffmpeg_proc = None

        self.status = "IDLE"
        self.status_message = "Recorder stopped"
        self.current_recording_filename = None

    def split_segment(self) -> bool:
        """Finalizes the currently active recording segment immediately and starts a new segment."""
        if self.is_running:
            with self.proc_lock:
                proc = self.ffmpeg_proc
                if proc is not None and proc.poll() is None:
                    print("[NVR Recorder] Split requested. Gracefully finalizing current clip with 'q' signal...")
                    try:
                        if proc.stdin:
                            proc.stdin.write(b"q")
                            proc.stdin.flush()
                        proc.wait(timeout=3)
                    except Exception:
                        try:
                            proc.kill()
                        except Exception:
                            pass
                    self.split_requested.set()
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
        Builds FFmpeg command based on quality profile:
        - 480p_10fps (Default): 854x480 @ 10 FPS, 220k bitrate (~2.06 GB / day -> ~3.9 days in 8GB).
        - 360p_10fps: 640x360 @ 10 FPS, 150k bitrate (~1.60 GB / day -> ~5.0 days in 8GB).
        - 720p_native: 1280x720 @ 15 FPS from stream2 (~4.68 GB / day -> ~1.7 days in 8GB).
        - 1080p_full: 1920x1080 @ 15 FPS from stream1 (~15.73 GB / day -> ~12 Hours in 8GB).
        """
        output_path = str(RECORDINGS_DIR / output_filename)
        input_url = self.rtsp_url

        if self.quality_profile == "480p_10fps":
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "5000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", input_url,
                "-t", str(self.segment_duration),
                "-vf", "scale=854:480,fps=10",
                "-g", "20",                          # Force keyframe every 2 seconds for clean segment finalization
                "-c:v", "libx264",
                "-preset", "ultrafast",
                "-b:v", "220k",
                "-maxrate", "280k",
                "-bufsize", "500k",
                "-pix_fmt", "yuv420p",
                "-c:a", "aac",
                "-b:a", "32k",
                "-movflags", "+faststart",
                output_path
            ]
        elif self.quality_profile == "360p_10fps":
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "5000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", input_url,
                "-t", str(self.segment_duration),
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
                "-movflags", "+faststart",
                output_path
            ]
        elif self.quality_profile == "720p_native":
            sub_url = input_url.replace("/stream1", "/stream2")
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "5000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", sub_url,
                "-t", str(self.segment_duration),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "64k",
                "-movflags", "+faststart",
                output_path
            ]
        else:  # 1080p_full
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "warning",
                "-rtsp_transport", "tcp",
                "-timeout", "5000000",
                "-fflags", "+genpts+discardcorrupt",
                "-i", input_url,
                "-t", str(self.segment_duration),
                "-c:v", "copy",
                "-c:a", "aac",
                "-b:a", "64k",
                "-movflags", "+faststart",
                output_path
            ]

        return cmd

    def _recording_loop(self):
        """Supervisor loop that records consecutive 15-minute segments 24/7 with auto-reconnect."""
        while not self.stop_event.is_set():
            # 1. Proactive Probe: Wait until camera is physically reachable
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
            print(f"[NVR Recorder] Camera online! Starting new {self.quality_profile} segment: {output_filename}...")

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

                stall_counter = 0
                last_size = -1

                # 3. Active Watchdog: Monitor process health and file growth
                while not self.stop_event.is_set():
                    poll_code = proc.poll()
                    if poll_code is not None:
                        # Process exited on its own (natural 15-minute completion)
                        print(f"[NVR Recorder] Segment {output_filename} completed cleanly (code {poll_code}). Auto-advancing to next segment...")
                        break

                    time.sleep(1.5)

                    # Check if active file is growing
                    filepath = RECORDINGS_DIR / output_filename
                    if filepath.exists():
                        current_size = filepath.stat().st_size
                        elapsed = time.time() - self.segment_start_time

                        # Check if 15 minutes reached -> Gracefully send 'q' to finalize
                        if elapsed >= self.segment_duration and proc.stdin:
                            try:
                                proc.stdin.write(b"q")
                                proc.stdin.flush()
                            except Exception:
                                pass

                        if current_size == last_size and elapsed > 25:
                            stall_counter += 1
                            if stall_counter >= 6:  # Stalled for >25 seconds
                                print(f"[NVR Recorder] Stream stalled on {output_filename}. Restarting recorder...")
                                try:
                                    proc.kill()
                                except Exception:
                                    pass
                                break
                        else:
                            stall_counter = 0
                            last_size = current_size

            except Exception as e:
                print(f"[NVR Recorder] Error running FFmpeg on {output_filename}: {e}")

            # Ensure clean wait for FFmpeg to finish writing moov atom
            if proc is not None:
                try:
                    proc.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            with self.proc_lock:
                self.ffmpeg_proc = None

            # Small delay to let filesystem settle
            time.sleep(0.2)

            # Generate thumbnail or cleanup if empty/corrupted
            completed_file = RECORDINGS_DIR / output_filename
            if completed_file.exists():
                if completed_file.stat().st_size > 30000:
                    thumb_file = THUMBNAILS_DIR / f"{completed_file.stem}.jpg"
                    self._generate_thumbnail(completed_file, thumb_file)
                else:
                    try:
                        completed_file.unlink(missing_ok=True)
                    except Exception:
                        pass

            if not self.stop_event.is_set():
                self.status = "RECONNECTING"
                backoff = 2.0 if (proc is None or proc.poll() != 0) else 0.2
                self.status_message = "Starting next recording segment..."
                time.sleep(backoff)

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
                    if not thumb_path.exists() and clip.stat().st_size > 30000:
                        self._generate_thumbnail(clip, thumb_path)

                # 2. Enforce storage limit
                freed, deleted = self.storage_mgr.cleanup_if_needed()
                if deleted:
                    print(f"[NVR Recorder] Storage cleanup freed {freed / (1024*1024):.1f} MB ({len(deleted)} clips).")

            except Exception as e:
                print(f"[NVR Recorder] Watcher error: {e}")

            time.sleep(10.0)

    def _generate_thumbnail(self, video_path: Path, thumb_path: Path) -> bool:
        """Extracts a lightweight JPG thumbnail from video segment using OpenCV."""
        try:
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                cap.release()
                print(f"[NVR Recorder] Warning: Video file {video_path.name} cannot be opened by OpenCV.")
                return False

            cap.set(cv2.CAP_PROP_POS_MSEC, 1000)
            ret, frame = cap.read()
            if not ret:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()

            if ret and frame is not None:
                thumb = cv2.resize(frame, (400, 225), interpolation=cv2.INTER_AREA)
                cv2.imwrite(str(thumb_path), thumb, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
                cap.release()
                return True
            
            cap.release()
            return False
        except Exception as e:
            print(f"[NVR Recorder] Thumbnail creation error for {video_path.name}: {e}")
            return False
