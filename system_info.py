import os
import sys
import time
import platform
import subprocess
from pathlib import Path
from typing import Dict, Any

def get_cpu_temp() -> float:
    """Reads Raspberry Pi CPU temperature or returns fallback on non-Pi."""
    try:
        # Standard Linux thermal zone (Raspberry Pi OS)
        temp_file = Path("/sys/class/thermal/thermal_zone0/temp")
        if temp_file.exists():
            millidegrees = int(temp_file.read_text().strip())
            return round(millidegrees / 1000.0, 1)

        # Fallback: vcgencmd on Raspberry Pi
        res = subprocess.run(["vcgencmd", "measure_temp"], capture_output=True, text=True, timeout=1)
        if res.returncode == 0 and "temp=" in res.stdout:
            temp_str = res.stdout.replace("temp=", "").replace("'C", "").strip()
            return float(temp_str)
    except Exception:
        pass
    return 42.0  # Simulated normal temp on non-Pi host

def get_system_metrics() -> Dict[str, Any]:
    """Returns Raspberry Pi / Host system health status."""
    metrics = {
        "platform": platform.system(),
        "arch": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_temp": get_cpu_temp(),
        "cpu_load_percent": 0.0,
        "ram_used_mb": 0,
        "ram_total_mb": 0,
        "ram_percent": 0.0,
    }

    # Memory info on Linux / Pi
    try:
        meminfo = Path("/proc/meminfo")
        if meminfo.exists():
            mem_data = {}
            for line in meminfo.read_text().splitlines():
                parts = line.split(":")
                if len(parts) == 2:
                    key = parts[0].strip()
                    val = parts[1].strip().split()[0]
                    mem_data[key] = int(val)
            
            total_kb = mem_data.get("MemTotal", 1)
            avail_kb = mem_data.get("MemAvailable", mem_data.get("MemFree", 0))
            used_kb = total_kb - avail_kb
            
            metrics["ram_total_mb"] = round(total_kb / 1024, 1)
            metrics["ram_used_mb"] = round(used_kb / 1024, 1)
            metrics["ram_percent"] = round((used_kb / total_kb) * 100, 1)
    except Exception:
        pass

    # CPU Load
    try:
        if hasattr(os, 'getloadavg'):
            loads = os.getloadavg()
            metrics["cpu_load_percent"] = round(loads[0] * 100 / (os.cpu_count() or 1), 1)
    except Exception:
        pass

    return metrics
