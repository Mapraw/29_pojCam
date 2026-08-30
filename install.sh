#!/bin/bash
# ==============================================================================
# Universal Linux Setup Script for RTSP Camera NVR & Mobile Web Server
# Compatible with Ubuntu, Debian, Armbian, Arch, Fedora, etc.
# ==============================================================================

set -e

echo "🐧 Setting up RTSP Camera NVR on Linux System..."

CURRENT_USER=$(whoami)
CURRENT_DIR=$(pwd)

echo "-> Detected User: $CURRENT_USER"
echo "-> Working Directory: $CURRENT_DIR"

# 1. Install System Packages (FFmpeg, Python3, OpenCV)
echo "[1/4] Installing system packages..."
if command -v apt-get &> /dev/null; then
    sudo apt-get update -y
    sudo apt-get install -y ffmpeg python3 python3-pip python3-venv python3-opencv python3-flask python3-numpy python3-pil
elif command -v dnf &> /dev/null; then
    sudo dnf install -y ffmpeg python3 python3-pip python3-opencv
elif command -v pacman &> /dev/null; then
    sudo pacman -Sy --noconfirm ffmpeg python python-pip python-opencv
else
    echo "Warning: Package manager not recognized. Please ensure ffmpeg and python3 are installed."
fi

# 2. Setup Python Virtual Environment (Handles modern Linux PEP 668 externally-managed)
echo "[2/4] Setting up Python environment..."
if [ ! -d "venv" ]; then
    python3 -m venv venv --system-site-packages 2>/dev/null || python3 -m venv venv
fi
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 3. Create required directories
echo "[3/4] Initializing storage directories..."
mkdir -p recordings/thumbnails snapshots

# 4. Set up systemd background auto-start service
echo "[4/4] Configuring systemd background auto-start service..."
SERVICE_FILE="/etc/systemd/system/camera-nvr.service"

cat <<EOF | sudo tee $SERVICE_FILE
[Unit]
Description=RTSP Camera NVR & Mobile Stream Server
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=${CURRENT_USER}
WorkingDirectory=${CURRENT_DIR}
ExecStart=${CURRENT_DIR}/venv/bin/python ${CURRENT_DIR}/app.py --no-browser
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable camera-nvr.service
sudo systemctl restart camera-nvr.service

IP_ADDR=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "localhost")

echo ""
echo "================================================================="
echo "  ✅ LINUX SERVER INSTALLATION COMPLETE!"
echo "  The camera server is now running in the background as a service."
echo ""
echo "  📱 Open on your smartphone or PC browser:"
echo "     http://${IP_ADDR}:5000"
echo ""
echo "  Useful service commands:"
echo "     sudo systemctl status camera-nvr    # Check status"
echo "     sudo systemctl restart camera-nvr   # Restart server"
echo "     journalctl -u camera-nvr -f         # View live logs"
echo "================================================================="
