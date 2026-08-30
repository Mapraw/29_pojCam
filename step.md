# 🐧 Step-by-Step Guide: Universal Linux Deployment (Auto-Starts on Boot)

This guide walks you through deploying the **Camera NVR & Streaming Server** onto any **Linux-based system** (Ubuntu, Debian, Armbian, etc.) and setting it to automatically start on boot via `systemd`.

---

## 📋 Prerequisites
1. Your Linux machine is powered on and connected to the same local network / Wi-Fi as your camera.
2. You know your Linux username (e.g. `ubuntu`, `debian`, `pi`, or your custom username) and its IP address (e.g. `192.168.1.xxx`).

> [!TIP]
> **To find your Linux IP address:**
> On the Linux terminal, run: `hostname -I` or `ip a`

---

## 🚀 Step 1: Copy Files from PC to Linux Machine

Open **PowerShell** or **Command Prompt** on your PC and run:

```powershell
scp -r "C:\Users\Jarup\Desktop\RICH\29_cam_pen" <USERNAME>@<LINUX_IP>:~/camera_server
```

*Example (if your Linux username is `ubuntu` and IP is `192.168.1.100`):*
```powershell
scp -r "C:\Users\Jarup\Desktop\RICH\29_cam_pen" ubuntu@192.168.1.100:~/camera_server
```
*(Enter your Linux password when prompted).*

---

## 💻 Step 2: SSH into Your Linux Machine

From PowerShell or terminal:

```powershell
ssh <USERNAME>@<LINUX_IP>
```

---

## ⚡ Step 3: Run the Universal Setup Script

Once logged into your Linux terminal, run:

```bash
cd ~/camera_server
chmod +x install.sh
./install.sh
```

### What this script does automatically:
1. Detects your package manager (`apt`, `dnf`, or `pacman`) and installs **FFmpeg**, **Python 3**, and **OpenCV**.
2. Creates an isolated Python virtual environment (`venv`) to ensure smooth compatibility with modern Linux distributions.
3. Installs required packages (`Flask`, `Pillow`, `numpy`).
4. Creates storage folders (`recordings/` and `snapshots/`).
5. Configures and registers **`camera-nvr.service`** with `systemd` so it **runs in the background and starts automatically every time Linux boots up**.

---

## 📱 Step 4: Open on Your Smartphone or PC

Open any browser on your smartphone or PC connected to your home network:

👉 **`http://<LINUX_IP>:5000`**

*(Example: `http://192.168.1.100:5000`)*

---

## 🛠️ Handy Linux Service Commands

You do not need to run commands when you turn on or reboot the machine, but here are useful maintenance commands:

| Action | Command |
| :--- | :--- |
| **Check Live Status** | `sudo systemctl status camera-nvr` |
| **View Real-Time Server Logs** | `journalctl -u camera-nvr -f` |
| **Restart the Camera Server** | `sudo systemctl restart camera-nvr` |
| **Stop the Camera Server** | `sudo systemctl stop camera-nvr` |
| **Disable Auto-Start** | `sudo systemctl disable camera-nvr` |

---

## 🔄 Step 5: Test Auto-Start on System Reboot

To confirm that the server starts up automatically with zero human commands:

1. Reboot your Linux system:
   ```bash
   sudo reboot
   ```
2. Wait 30–45 seconds for Linux to reboot.
3. Open your smartphone browser to **`http://<LINUX_IP>:5000`**.
4. The live stream, 15-minute chunk recording, and 4GB storage manager will already be running!
