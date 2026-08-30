import cv2
import os
import time
import socket
import subprocess
import threading
import numpy as np
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_URL_FILE = BASE_DIR / "high_qual.txt"
SNAPSHOTS_DIR = BASE_DIR / "snapshots"
RECORDINGS_DIR = BASE_DIR / "recordings"

SNAPSHOTS_DIR.mkdir(exist_ok=True)
RECORDINGS_DIR.mkdir(exist_ok=True)


class RTSPStreamManager:
    def __init__(self, url_file=DEFAULT_URL_FILE):
        self.url_file = Path(url_file)
        self.rtsp_url = self.load_url()
        self.transport = "tcp"  # "tcp" or "udp"
        
        # State
        self.is_running = False
        self.status = "DISCONNECTED"  # CONNECTING, ONLINE, RECONNECTING, ERROR, DISCONNECTED
        self.status_message = "Stream initialized"
        self.current_frame = None
        self.frame_lock = threading.Lock()
        self.frame_count = 0
        self.fps = 0.0
        self.last_frame_time = 0
        self.width = 0
        self.height = 0
        self.reconnect_interval = 3.0  # seconds

        # Image processing filters
        self.brightness = 0  # -100 to 100
        self.contrast = 1.0  # 0.5 to 3.0
        self.flip_h = False
        self.flip_v = False
        self.rotate_angle = 0  # 0, 90, 180, 270

        # Video recording
        self.is_recording = False
        self.recording_writer = None
        self.recording_filename = None
        self.recording_start_time = None
        self.recording_frames = 0
        self.recording_lock = threading.Lock()

        # Thread controls
        self.capture_thread = None
        self.stop_event = threading.Event()

    def load_url(self) -> str:
        """Loads the RTSP URL from file or returns default."""
        if self.url_file.exists():
            try:
                content = self.url_file.read_text(encoding="utf-8").strip()
                if content:
                    return content
            except Exception as e:
                print(f"[StreamManager] Error reading {self.url_file}: {e}")
        return "rtsp://127.0.0.1:554/live"

    def save_url(self, new_url: str) -> bool:
        """Saves new RTSP URL to file and restarts stream if changed."""
        new_url = new_url.strip()
        if not new_url:
            return False
        try:
            self.url_file.write_text(new_url, encoding="utf-8")
            self.rtsp_url = new_url
            # Restart capture with new URL
            if self.is_running:
                self.restart()
            return True
        except Exception as e:
            print(f"[StreamManager] Error saving URL: {e}")
            return False

    def update_settings(self, transport=None, brightness=None, contrast=None, flip_h=None, flip_v=None, rotate=None):
        """Update stream settings dynamically."""
        restart_needed = False
        if transport and transport in ("tcp", "udp") and transport != self.transport:
            self.transport = transport
            restart_needed = True

        if brightness is not None:
            self.brightness = int(brightness)
        if contrast is not None:
            self.contrast = float(contrast)
        if flip_h is not None:
            self.flip_h = bool(flip_h)
        if flip_v is not None:
            self.flip_v = bool(flip_v)
        if rotate is not None and int(rotate) in (0, 90, 180, 270):
            self.rotate_angle = int(rotate)

        if restart_needed and self.is_running:
            self.restart()

    def start(self):
        """Starts the background capture thread."""
        if self.is_running:
            return
        self.is_running = True
        self.stop_event.clear()
        self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.capture_thread.start()

    def stop(self):
        """Stops the stream capture."""
        self.is_running = False
        self.stop_event.set()
        self.stop_recording()
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=2.0)
        self.status = "DISCONNECTED"
        self.status_message = "Stream stopped"

    def restart(self):
        """Restarts the capture thread."""
        self.stop()
        time.sleep(0.5)
        self.start()

    def _apply_filters(self, frame):
        """Applies brightness, contrast, flips, and rotation."""
        if frame is None:
            return None
        
        out = frame
        # Brightness and Contrast
        if self.brightness != 0 or self.contrast != 1.0:
            out = cv2.convertScaleAbs(out, alpha=self.contrast, beta=self.brightness)

        # Flips
        if self.flip_h and self.flip_v:
            out = cv2.flip(out, -1)
        elif self.flip_h:
            out = cv2.flip(out, 1)
        elif self.flip_v:
            out = cv2.flip(out, 0)

        # Rotation
        if self.rotate_angle == 90:
            out = cv2.rotate(out, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotate_angle == 180:
            out = cv2.rotate(out, cv2.ROTATE_180)
        elif self.rotate_angle == 270:
            out = cv2.rotate(out, cv2.ROTATE_90_COUNTERCLOCKWISE)

        return out

    def _get_live_url(self) -> str:
        """Returns stream2 (substream) for live viewing if available to prevent session collision with NVR recorder."""
        if "/stream1" in self.rtsp_url:
            return self.rtsp_url.replace("/stream1", "/stream2")
        return self.rtsp_url

    def _check_reachable(self, timeout: float = 1.5) -> bool:
        """Probes RTSP host and port to verify camera is physically online."""
        try:
            url = self.rtsp_url
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

    def _capture_loop(self):
        """Dedicated background loop that fetches RTSP frames using FFmpeg rawvideo pipe with instant auto-reconnect."""
        width = 854
        height = 480
        frame_size = width * height * 3

        while not self.stop_event.is_set():
            # 1. Proactively verify camera socket is open before attempting capture
            if not self._check_reachable():
                self.status = "OFFLINE"
                self.status_message = "Camera offline (unplugged or rebooting)..."
                time.sleep(2.0)
                continue

            self.status = "CONNECTING"
            self.status_message = f"Connecting via {self.transport.upper()}..."

            live_url = self._get_live_url()
            cmd = [
                "ffmpeg",
                "-hide_banner",
                "-loglevel", "quiet",
                "-rtsp_transport", self.transport,
                "-timeout", "3000000",             # 3-second socket timeout so disconnects immediately abort
                "-fflags", "+genpts+discardcorrupt",
                "-i", live_url,
                "-f", "image2pipe",
                "-pix_fmt", "bgr24",
                "-vcodec", "rawvideo",
                "-s", f"{width}x{height}",
                "-"
            ]

            proc = None
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.DEVNULL,
                    bufsize=frame_size * 2
                )

                self.status = "ONLINE"
                self.status_message = "Live stream active"
                self.width = width
                self.height = height

                fps_count = 0
                fps_timer = time.time()

                while not self.stop_event.is_set():
                    raw_frame = proc.stdout.read(frame_size)
                    if len(raw_frame) != frame_size:
                        print("[StreamManager] Stream disconnected / EOF from camera. Reconnecting...")
                        self.status = "RECONNECTING"
                        self.status_message = "Connection lost (camera rebooting). Reconnecting..."
                        break

                    frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((height, width, 3))

                    now = time.time()
                    self.last_frame_time = now
                    fps_count += 1

                    if now - fps_timer >= 1.0:
                        self.fps = round(fps_count / (now - fps_timer), 1)
                        fps_count = 0
                        fps_timer = now

                    # Process filters (flip, rotate, brightness)
                    processed_frame = self._apply_filters(frame)

                    with self.frame_lock:
                        self.current_frame = processed_frame
                        self.frame_count += 1

            except Exception as e:
                self.status = "ERROR"
                self.status_message = f"Stream exception: {str(e)}"
            finally:
                if proc is not None:
                    try:
                        proc.kill()
                        proc.wait()
                    except Exception:
                        pass

            if not self.stop_event.is_set():
                time.sleep(1.0)

    def get_latest_frame(self):
        """Returns the most recent frame or a generated placeholder."""
        with self.frame_lock:
            if self.current_frame is not None and (time.time() - self.last_frame_time) < 3.0:
                return self.current_frame.copy()
            
        return self._generate_placeholder()

    def _generate_placeholder(self):
        """Creates a smooth animated/styled dark placeholder frame when stream is offline/connecting."""
        w, h = 1280, 720
        frame = np.zeros((h, w, 3), dtype=np.uint8)
        frame[:] = (20, 24, 30)  # Dark slate background

        # Grid lines for tech feel
        for x in range(0, w, 80):
            cv2.line(frame, (x, 0), (x, h), (30, 36, 46), 1)
        for y in range(0, h, 80):
            cv2.line(frame, (0, y), (w, y), (30, 36, 46), 1)

        # Center box
        cx, cy = w // 2, h // 2
        cv2.rectangle(frame, (cx - 280, cy - 110), (cx + 280, cy + 110), (35, 45, 58), -1)
        cv2.rectangle(frame, (cx - 280, cy - 110), (cx + 280, cy + 110), (70, 85, 110), 1)

        # Status text colors
        color_map = {
            "ONLINE": (50, 205, 50),
            "CONNECTING": (255, 191, 0),
            "RECONNECTING": (255, 140, 0),
            "ERROR": (70, 70, 240),
            "DISCONNECTED": (128, 128, 128)
        }
        status_color = color_map.get(self.status, (200, 200, 200))

        # Title
        cv2.putText(frame, "RTSP CAMERA STREAM", (cx - 190, cy - 50), 
                    cv2.FONT_HERSHEY_DUPLEX, 0.9, (230, 235, 245), 2, cv2.LINE_AA)
        
        # Status indicator circle
        cv2.circle(frame, (cx - 170, cy), 8, status_color, -1)
        cv2.putText(frame, f"STATUS: {self.status}", (cx - 145, cy + 7), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, status_color, 2, cv2.LINE_AA)
        
        # Status details
        cv2.putText(frame, self.status_message, (cx - 240, cy + 50), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (160, 175, 195), 1, cv2.LINE_AA)
        
        # URL indicator at bottom
        url_display = self.rtsp_url if len(self.rtsp_url) < 65 else self.rtsp_url[:62] + "..."
        cv2.putText(frame, f"Target: {url_display}", (cx - 250, cy + 80), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (110, 130, 150), 1, cv2.LINE_AA)

        # Timestamp
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cv2.putText(frame, ts, (25, h - 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (100, 120, 140), 1, cv2.LINE_AA)

        return frame

    def capture_snapshot(self) -> str:
        """Captures the current frame and saves to snapshots directory."""
        frame = self.get_latest_frame()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"snapshot_{timestamp}.jpg"
        filepath = SNAPSHOTS_DIR / filename
        cv2.imwrite(str(filepath), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
        return filename

    def start_recording(self) -> tuple[bool, str]:
        """Starts recording the stream to an MP4/AVI file."""
        with self.recording_lock:
            if self.is_recording:
                return False, "Already recording"

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.recording_filename = f"record_{timestamp}.mp4"
            filepath = RECORDINGS_DIR / self.recording_filename

            frame = self.get_latest_frame()
            h, w = frame.shape[:2]

            # Use mp4v or XVID codec
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            fps_target = max(15.0, self.fps if self.fps > 5 else 25.0)

            self.recording_writer = cv2.VideoWriter(str(filepath), fourcc, fps_target, (w, h))
            if not self.recording_writer.isOpened():
                # Fallback to AVI with XVID if mp4v fails
                self.recording_filename = f"record_{timestamp}.avi"
                filepath = RECORDINGS_DIR / self.recording_filename
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                self.recording_writer = cv2.VideoWriter(str(filepath), fourcc, fps_target, (w, h))

            self.is_recording = True
            self.recording_start_time = time.time()
            self.recording_frames = 0
            return True, self.recording_filename

    def stop_recording(self) -> tuple[bool, str]:
        """Stops the current recording and releases writer."""
        with self.recording_lock:
            if not self.is_recording:
                return False, "Not recording"

            self.is_recording = False
            filename = self.recording_filename
            if self.recording_writer is not None:
                self.recording_writer.release()
                self.recording_writer = None

            duration = round(time.time() - (self.recording_start_time or time.time()), 1)
            msg = f"Saved {filename} ({duration}s, {self.recording_frames} frames)"
            self.recording_filename = None
            self.recording_start_time = None
            return True, msg

    def get_status(self) -> dict:
        """Returns the current status dictionary for UI updates."""
        rec_duration = 0
        if self.is_recording and self.recording_start_time:
            rec_duration = round(time.time() - self.recording_start_time, 1)

        return {
            "status": self.status,
            "status_message": self.status_message,
            "rtsp_url": self.rtsp_url,
            "transport": self.transport,
            "fps": self.fps,
            "width": self.width,
            "height": self.height,
            "frame_count": self.frame_count,
            "is_recording": self.is_recording,
            "recording_file": self.recording_filename,
            "recording_duration": rec_duration,
            "brightness": self.brightness,
            "contrast": self.contrast,
            "flip_h": self.flip_h,
            "flip_v": self.flip_v,
            "rotate_angle": self.rotate_angle,
        }
