import os
import sys
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk
import cv2

from stream_manager import RTSPStreamManager, SNAPSHOTS_DIR, RECORDINGS_DIR

class DesktopStreamerApp:
    def __init__(self, root):
        self.root = root
        self.root.title("RTSP Camera Streamer - High Quality")
        self.root.geometry("1100x750")
        self.root.minsize(800, 500)
        self.root.configure(bg="#12151c")

        self.manager = RTSPStreamManager()
        self.manager.start()

        self.is_fullscreen = False
        self.zoom_level = 1.0

        self._setup_style()
        self._setup_ui()
        self._bind_shortcuts()

        self.update_interval_ms = 30  # ~33 fps GUI refresh
        self.root.after(100, self._update_loop)

    def _setup_style(self):
        self.style = ttk.Style()
        self.style.theme_use("clam")
        
        # Configure dark colors
        bg_dark = "#12151c"
        card_bg = "#1b202c"
        text_color = "#e2e8f0"
        accent_color = "#3b82f6"

        self.style.configure("TFrame", background=bg_dark)
        self.style.configure("Card.TFrame", background=card_bg, relief="flat")
        self.style.configure("TLabel", background=bg_dark, foreground=text_color, font=("Segoe UI", 10))
        self.style.configure("Header.TLabel", background=card_bg, foreground="#ffffff", font=("Segoe UI", 12, "bold"))
        self.style.configure("Status.TLabel", background=card_bg, foreground="#94a3b8", font=("Segoe UI", 9))
        self.style.configure("TButton", background="#2d3748", foreground="#ffffff", font=("Segoe UI", 9, "bold"), borderwidth=0, padding=6)
        self.style.map("TButton",
                       background=[("active", "#4a5568"), ("pressed", "#1a202c")],
                       foreground=[("active", "#ffffff")])

        self.style.configure("Accent.TButton", background=accent_color, foreground="#ffffff")
        self.style.map("Accent.TButton",
                       background=[("active", "#2563eb"), ("pressed", "#1d4ed8")])

        self.style.configure("Record.TButton", background="#dc2626", foreground="#ffffff")
        self.style.map("Record.TButton",
                       background=[("active", "#b91c1c"), ("pressed", "#991b1b")])

    def _setup_ui(self):
        # Top App Bar
        self.top_bar = ttk.Frame(self.root, style="Card.TFrame", padding=(15, 10))
        self.top_bar.pack(fill="x", side="top")

        # Title & URL
        title_box = ttk.Frame(self.top_bar, style="Card.TFrame")
        title_box.pack(side="left", fill="y")
        
        lbl_title = ttk.Label(title_box, text="🎥 RTSP Live Stream", style="Header.TLabel")
        lbl_title.pack(anchor="w")

        self.lbl_url = ttk.Label(title_box, text=f"Source: {self.manager.rtsp_url}", style="Status.TLabel")
        self.lbl_url.pack(anchor="w")

        # Top Right Controls
        btn_box = ttk.Frame(self.top_bar, style="Card.TFrame")
        btn_box.pack(side="right", fill="y")

        self.btn_edit_url = ttk.Button(btn_box, text="⚙️ Settings", command=self._open_settings_dialog)
        self.btn_edit_url.pack(side="right", padx=4)

        self.btn_reconnect = ttk.Button(btn_box, text="🔄 Reconnect", command=self._reconnect)
        self.btn_reconnect.pack(side="right", padx=4)

        # Video Canvas Area
        self.video_container = tk.Frame(self.root, bg="#0b0e14")
        self.video_container.pack(fill="both", expand=True, padx=10, pady=10)

        self.canvas = tk.Canvas(self.video_container, bg="#0b0e14", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Bottom Action Bar
        self.bottom_bar = ttk.Frame(self.root, style="Card.TFrame", padding=(15, 10))
        self.bottom_bar.pack(fill="x", side="bottom")

        # Status Indicators
        status_box = ttk.Frame(self.bottom_bar, style="Card.TFrame")
        status_box.pack(side="left")

        self.lbl_status_dot = tk.Label(status_box, text="●", font=("Segoe UI", 14), bg="#1b202c", fg="#eab308")
        self.lbl_status_dot.pack(side="left", padx=(0, 6))

        self.lbl_status_text = ttk.Label(status_box, text="Connecting...", style="Header.TLabel")
        self.lbl_status_text.pack(side="left", padx=(0, 15))

        self.lbl_stats = ttk.Label(status_box, text="FPS: -- | Res: --", style="Status.TLabel")
        self.lbl_stats.pack(side="left")

        # Action Buttons (Right)
        actions_box = ttk.Frame(self.bottom_bar, style="Card.TFrame")
        actions_box.pack(side="right")

        self.btn_snapshot = ttk.Button(actions_box, text="📸 Snapshot", style="Accent.TButton", command=self._take_snapshot)
        self.btn_snapshot.pack(side="left", padx=5)

        self.btn_record = ttk.Button(actions_box, text="⏺️ Start Record", style="Record.TButton", command=self._toggle_recording)
        self.btn_record.pack(side="left", padx=5)

        self.btn_fullscreen = ttk.Button(actions_box, text="⛶ Fullscreen", command=self._toggle_fullscreen)
        self.btn_fullscreen.pack(side="left", padx=5)

        self.btn_open_folder = ttk.Button(actions_box, text="📁 Media Folder", command=self._open_folder)
        self.btn_open_folder.pack(side="left", padx=5)

    def _bind_shortcuts(self):
        self.root.bind("<F11>", lambda e: self._toggle_fullscreen())
        self.root.bind("<Escape>", lambda e: self._exit_fullscreen())
        self.root.bind("<s>", lambda e: self._take_snapshot())
        self.root.bind("<r>", lambda e: self._toggle_recording())

    def _update_loop(self):
        try:
            frame = self.manager.get_latest_frame()
            if frame is not None:
                # Resize frame to fit canvas while maintaining aspect ratio
                canvas_w = max(100, self.canvas.winfo_width())
                canvas_h = max(100, self.canvas.winfo_height())
                fh, fw = frame.shape[:2]

                ratio = min(canvas_w / fw, canvas_h / fh)
                nw, nh = int(fw * ratio), int(fh * ratio)

                if nw > 0 and nh > 0:
                    resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_AREA)
                    rgb_frame = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb_frame)
                    self.tk_image = ImageTk.PhotoImage(image=img)
                    
                    self.canvas.delete("all")
                    self.canvas.create_image(canvas_w // 2, canvas_h // 2, anchor=tk.CENTER, image=self.tk_image)

            # Update Status Labels
            status = self.manager.get_status()
            self.lbl_status_text.config(text=status["status"])
            
            dot_color = {
                "ONLINE": "#22c55e",
                "CONNECTING": "#eab308",
                "RECONNECTING": "#f97316",
                "ERROR": "#ef4444",
                "DISCONNECTED": "#64748b"
            }.get(status["status"], "#94a3b8")
            self.lbl_status_dot.config(fg=dot_color)

            stats_msg = f"FPS: {status['fps']} | Res: {status['width']}x{status['height']}"
            if status["is_recording"]:
                stats_msg += f" | 🔴 REC {status['recording_duration']}s"
                self.btn_record.config(text=f"⏹️ Stop ({status['recording_duration']}s)")
            else:
                self.btn_record.config(text="⏺️ Start Record")

            self.lbl_stats.config(text=stats_msg)

        except Exception as e:
            pass

        self.root.after(self.update_interval_ms, self._update_loop)

    def _take_snapshot(self):
        try:
            filename = self.manager.capture_snapshot()
            messagebox.showinfo("Snapshot Saved", f"Snapshot captured successfully:\n{filename}\n\nSaved in: {SNAPSHOTS_DIR}")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to capture snapshot: {e}")

    def _toggle_recording(self):
        if not self.manager.is_recording:
            success, msg = self.manager.start_recording()
            if not success:
                messagebox.showerror("Recording Error", msg)
        else:
            success, msg = self.manager.stop_recording()
            if success:
                messagebox.showinfo("Recording Saved", f"{msg}\n\nSaved in: {RECORDINGS_DIR}")

    def _toggle_fullscreen(self):
        self.is_fullscreen = not self.is_fullscreen
        self.root.attributes("-fullscreen", self.is_fullscreen)
        if self.is_fullscreen:
            self.top_bar.pack_forget()
            self.bottom_bar.pack_forget()
        else:
            self.top_bar.pack(fill="x", side="top")
            self.bottom_bar.pack(fill="x", side="bottom")

    def _exit_fullscreen(self):
        if self.is_fullscreen:
            self._toggle_fullscreen()

    def _reconnect(self):
        self.manager.restart()

    def _open_folder(self):
        import subprocess
        subprocess.Popen(f'explorer "{BASE_DIR}"')

    def _open_settings_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title("Stream Settings & Adjustments")
        dialog.geometry("520x420")
        dialog.configure(bg="#1b202c")
        dialog.transient(self.root)
        dialog.grab_set()

        pad = {"padx": 15, "pady": 8}

        # RTSP URL
        tk.Label(dialog, text="RTSP Stream URL:", bg="#1b202c", fg="#ffffff", font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
        url_entry = tk.Entry(dialog, bg="#2d3748", fg="#ffffff", insertbackground="white", font=("Segoe UI", 10))
        url_entry.insert(0, self.manager.rtsp_url)
        url_entry.pack(fill="x", padx=15)

        # Transport Protocol
        tk.Label(dialog, text="Transport Protocol:", bg="#1b202c", fg="#ffffff", font=("Segoe UI", 10, "bold")).pack(anchor="w", **pad)
        transport_var = tk.StringVar(value=self.manager.transport)
        trans_frame = tk.Frame(dialog, bg="#1b202c")
        trans_frame.pack(anchor="w", padx=15)
        tk.Radiobutton(trans_frame, text="TCP (Reliable, default)", variable=transport_var, value="tcp", bg="#1b202c", fg="#ffffff", selectcolor="#2d3748").pack(side="left", padx=5)
        tk.Radiobutton(trans_frame, text="UDP (Lowest latency)", variable=transport_var, value="udp", bg="#1b202c", fg="#ffffff", selectcolor="#2d3748").pack(side="left", padx=5)

        # Brightness Slider
        tk.Label(dialog, text="Brightness (-100 to 100):", bg="#1b202c", fg="#ffffff", font=("Segoe UI", 9)).pack(anchor="w", padx=15, pady=(8, 0))
        brightness_scale = tk.Scale(dialog, from_=-100, to=100, orient="horizontal", bg="#1b202c", fg="#ffffff", highlightthickness=0)
        brightness_scale.set(self.manager.brightness)
        brightness_scale.pack(fill="x", padx=15)

        # Contrast Slider
        tk.Label(dialog, text="Contrast (0.5 to 3.0):", bg="#1b202c", fg="#ffffff", font=("Segoe UI", 9)).pack(anchor="w", padx=15, pady=(8, 0))
        contrast_scale = tk.Scale(dialog, from_=5, to=30, orient="horizontal", bg="#1b202c", fg="#ffffff", highlightthickness=0)
        contrast_scale.set(int(self.manager.contrast * 10))
        contrast_scale.pack(fill="x", padx=15)

        # Save Button
        def save_and_close():
            new_url = url_entry.get().strip()
            if new_url and new_url != self.manager.rtsp_url:
                self.manager.save_url(new_url)
                self.lbl_url.config(text=f"Source: {new_url}")

            self.manager.update_settings(
                transport=transport_var.get(),
                brightness=brightness_scale.get(),
                contrast=contrast_scale.get() / 10.0
            )
            dialog.destroy()

        btn_save = tk.Button(dialog, text="Save & Apply", bg="#3b82f6", fg="#ffffff", font=("Segoe UI", 10, "bold"), command=save_and_close, relief="flat", padx=15, pady=8)
        btn_save.pack(pady=20)

    def on_close(self):
        self.manager.stop()
        self.root.destroy()

if __name__ == "__main__":
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    root = tk.Tk()
    app = DesktopStreamerApp(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()
