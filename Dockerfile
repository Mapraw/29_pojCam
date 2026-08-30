# Lightweight Python & FFmpeg Docker Image for Raspberry Pi (ARM64 / ARMv7 / AMD64)
FROM python:3.11-slim

# Avoid interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install FFmpeg and OpenCV system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgl1 \
    libglib2.0-0 \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy dependencies first for caching
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Create volume directories
RUN mkdir -p recordings/thumbnails snapshots

# Expose web port
EXPOSE 5000

# Start camera server without launching desktop browser
CMD ["python", "app.py", "--no-browser"]
