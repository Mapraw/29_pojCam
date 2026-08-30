# 🍓 Raspberry Pi RTSP Camera NVR & Mobile Web Server

A lightweight, dedicated 24/7 **Micro-NVR** and **Mobile-First Web Server** for RTSP cameras, engineered specifically for Raspberry Pi (low CPU load, 4GB rolling storage FIFO retention, and smartphone playback).

---

## 🌟 Key Features

1. **⚡ Ultra-Low CPU Direct Stream Remuxing (`-c:v copy -c:a aac`)**:
   - Uses FFmpeg to copy video streams directly into MP4 containers without CPU re-encoding (**< 1% CPU usage on Raspberry Pi**).
   - Records crisp camera-quality segments with full **Audio Support (AAC)**.
   - Saves continuous **15-minute clips** (`900s` segments).

2. **🧹 4.0 GB Storage Pool & FIFO Rolling Retention**:
   - Maintains a maximum **4.0 GB hard limit** in the `recordings/` folder.
   - Automatically purges the oldest clips when storage reaches capacity (**FIFO auto-cleanup**).
   - **🔒 Clip Lock Protection**: Star / Lock important clips from the UI so they are never auto-deleted.

3. **📱 Smartphone-Compatible Web App (PWA Experience)**:
   - **Bottom Tab Navigation** optimized for iOS Safari & Android Chrome.
   - **🔴 Live Stream Tab**: Low-latency video preview, digital zoom & pan, live FPS & status.
   - **🎬 15-Min Clips Archive Tab**: Thumbnail gallery, timestamps, file sizes, and 🔥 **Motion Detection** badges.
   - **▶️ In-Browser HTML5 Video Player**: Uses **HTTP 206 Partial Content (Range Requests)** for instant seek/scrubbing on mobile, speed toggle (`0.5x`, `1.0x`, `1.5x`, `2.0x`), and 1-tap download to phone.
   - **📊 4GB Storage & Pi Health Tab**: Visual storage gauge, Pi CPU temperature (°C), and RAM monitor.

4. **🚀 24/7 Auto-Start on Raspberry Pi Boot**:
   - Runs automatically on Pi power-on without typing any commands! (Available via **Docker** or native **Systemd**).

---

## 🍓 Raspberry Pi Deployment & Auto-Start

You can choose either **Method 1 (Docker)** or **Method 2 (Native Systemd)**:

### 🐳 Method 1: Docker (Recommended)

1. **Copy folder to Raspberry Pi**:
   ```bash
   scp -r 29_cam_pen pi@<RASPBERRY_PI_IP>:/home/pi/camera_server
   ```

2. **SSH into Raspberry Pi and run the 1-click Docker script**:
   ```bash
   cd /home/pi/camera_server
   chmod +x deploy_docker.sh
   ./deploy_docker.sh
   ```

*(Docker will automatically install if not present, build the container, set `restart: unless-stopped`, and launch the app in the background. It will start automatically every time the Pi powers on!)*

- **View Logs**: `sudo docker compose logs -f`
- **Restart**: `sudo docker compose restart`
- **Stop**: `sudo docker compose down`

---

### ⚙️ Method 2: Native Linux Systemd Service

1. **Copy folder and run native installer**:
   ```bash
   cd /home/pi/camera_server
   chmod +x install.sh
   ./install.sh
   ```

*(This sets up `camera-nvr.service` via `systemd` to auto-start on boot).*

- **Check Status**: `sudo systemctl status camera-nvr`
- **Restart Service**: `sudo systemctl restart camera-nvr`
- **View Live Logs**: `journalctl -u camera-nvr -f`

---

## 📱 Accessing the Web App
Open your phone or computer browser:
```text
http://<RASPBERRY_PI_IP>:5000
```
# 29_pojCam
