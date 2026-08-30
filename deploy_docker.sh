#!/bin/bash
# ==============================================================================
# Deploy Camera NVR with Docker on Raspberry Pi (Auto-starts on Boot)
# ==============================================================================

set -e

echo "🍓 Deploying Camera NVR on Raspberry Pi using Docker..."

# 1. Install Docker & Docker Compose if not present
if ! command -v docker &> /dev/null; then
    echo "[1/3] Docker not found. Installing Docker on Raspberry Pi..."
    curl -fsSL https://get.docker.com -o get-docker.sh
    sudo sh get-docker.sh
    sudo usermod -aG docker $USER
    rm get-docker.sh
    echo "Docker installed successfully!"
else
    echo "[1/3] Docker is already installed."
fi

# 2. Build & Launch Docker Container in Background
echo "[2/3] Building and starting container in background..."
sudo docker compose up -d --build

# 3. Print access information
IP_ADDR=$(hostname -I | awk '{print $1}')
echo ""
echo "================================================================="
echo "  ✅ DOCKER DEPLOYMENT COMPLETE!"
echo "  The container is set to 'restart: unless-stopped'."
echo "  It will start automatically every time your Raspberry Pi turns on!"
echo ""
echo "  📱 Access Web UI from any phone or PC:"
echo "     http://${IP_ADDR}:5000"
echo ""
echo "  Useful Docker Commands:"
echo "     sudo docker compose logs -f    # View live logs"
echo "     sudo docker compose restart    # Restart container"
echo "     sudo docker compose down       # Stop container"
echo "================================================================="
