# 🍓 Raspberry Pi RTSP Multi-Camera NVR & Mobile Web Server

A lightweight, scalable 24/7 **Micro-NVR** and **Mobile-First Web Server** for RTSP cameras, engineered specifically for Raspberry Pi (low CPU load, rolling storage FIFO retention, cute mascot selection portal, and smartphone playback).

---

## 🌟 Key Features

1. **🐾 Multi-Camera Selection Hub with Cute 3D Mascot Cards**:
   - Welcome landing screen featuring cute 3D cartoon mascot cards for each camera.
   - 1-click entrance to any camera's live stream and recording archive.
   - Quick camera switcher in the top bar to toggle feeds seamlessly.
   - Built-in **Camera Manager** to add, edit, or delete cameras dynamically from the UI.

2. **⚡ Ultra-Low CPU Direct Stream Remuxing (`-c:v copy -c:a aac`)**:
   - Uses FFmpeg to copy video streams directly into MP4 containers without CPU re-encoding (**< 1% CPU usage on Raspberry Pi**).
   - Records crisp camera-quality segments with full **Audio Support (AAC)**.
   - Independent 24/7 background recording for all configured cameras into continuous **15-minute clips** (`900s` segments).

3. **🧹 Shared Storage Pool & FIFO Rolling Retention**:
   - Configurable storage hard limit (e.g. 8.0 GB) in the `recordings/` folder across all cameras.
   - Automatically purges oldest unlocked clips when storage reaches capacity (**FIFO auto-cleanup**).
   - **🔒 Clip Lock Protection**: Star / Lock important clips from the UI so they are never auto-deleted.

4. **📱 Smartphone-Compatible Web App (PWA Experience)**:
   - **🏠 Cameras Hub**: Choose which camera to inspect with cute cartoon cards.
   - **🔴 Live Stream Tab**: Low-latency video preview, digital zoom & pan, live FPS & status.
   - **🎬 15-Min Clips Archive Tab**: Filter clips by camera or view all, thumbnail gallery, timestamps, file sizes, and 🔥 **Motion Detection** badges.
   - **▶️ In-Browser HTML5 Video Player**: Uses **HTTP 206 Partial Content (Range Requests)** for instant seek/scrubbing on mobile, speed toggle (`0.5x`, `1.0x`, `1.5x`, `2.0x`), and 1-tap download to phone.
   - **📊 Storage & Pi Health Tab**: Visual storage gauge, Pi CPU temperature (°C), RAM monitor, and Camera Manager.

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
