import os
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional

BASE_DIR = Path(__file__).resolve().parent
RECORDINGS_DIR = BASE_DIR / "recordings"
THUMBNAILS_DIR = RECORDINGS_DIR / "thumbnails"
METADATA_FILE = RECORDINGS_DIR / "metadata.json"

RECORDINGS_DIR.mkdir(exist_ok=True)
THUMBNAILS_DIR.mkdir(exist_ok=True)

# Default: 8.0 GB Storage Cap (Upgraded for 2-3 day retention)
DEFAULT_MAX_STORAGE_BYTES = 8 * 1024 * 1024 * 1024  # 8 GB
DEFAULT_SOFT_LIMIT_RATIO = 0.94                     # Clean up when reaching 94% (approx 7.52 GB)
DEFAULT_TARGET_PURGE_RATIO = 0.82                   # Purge down to 82% (approx 6.56 GB)


class StorageManager:
    def __init__(self, recordings_dir: Path = RECORDINGS_DIR, max_storage_bytes: int = DEFAULT_MAX_STORAGE_BYTES):
        self.recordings_dir = Path(recordings_dir)
        self.thumbnails_dir = self.recordings_dir / "thumbnails"
        self.metadata_file = self.recordings_dir / "metadata.json"
        
        self.recordings_dir.mkdir(exist_ok=True)
        self.thumbnails_dir.mkdir(exist_ok=True)
        
        self.max_storage_bytes = max_storage_bytes
        self.soft_limit_bytes = int(self.max_storage_bytes * DEFAULT_SOFT_LIMIT_RATIO)
        self.target_purge_bytes = int(self.max_storage_bytes * DEFAULT_TARGET_PURGE_RATIO)
        
        self.metadata: Dict[str, Any] = self._load_metadata()

    def set_max_storage_gb(self, new_gb: float):
        """Dynamically updates the storage pool cap in gigabytes."""
        self.max_storage_bytes = int(new_gb * 1024 * 1024 * 1024)
        self.soft_limit_bytes = int(self.max_storage_bytes * DEFAULT_SOFT_LIMIT_RATIO)
        self.target_purge_bytes = int(self.max_storage_bytes * DEFAULT_TARGET_PURGE_RATIO)
        print(f"[StorageManager] Storage limit updated to {new_gb} GB ({self.max_storage_bytes} bytes).")

    def _load_metadata(self) -> Dict[str, Any]:
        """Loads clip metadata from JSON or returns empty dict."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                print(f"[StorageManager] Error reading metadata: {e}")
        return {}

    def _save_metadata(self):
        """Persists clip metadata safely to JSON."""
        try:
            temp_file = self.recordings_dir / "metadata.tmp"
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.metadata, f, indent=2, ensure_ascii=False)
            temp_file.replace(self.metadata_file)
        except Exception as e:
            print(f"[StorageManager] Error saving metadata: {e}")

    def get_total_used_bytes(self) -> int:
        """Calculates total size of recordings directory including thumbnails and clips."""
        total_size = 0
        for entry in self.recordings_dir.rglob("*"):
            if entry.is_file():
                try:
                    total_size += entry.stat().st_size
                except (OSError, FileNotFoundError):
                    pass
        return total_size

    def get_storage_info(self) -> Dict[str, Any]:
        """Returns comprehensive storage metrics."""
        used_bytes = self.get_total_used_bytes()
        used_mb = round(used_bytes / (1024 * 1024), 2)
        max_mb = round(self.max_storage_bytes / (1024 * 1024), 2)
        used_gb = round(used_bytes / (1024 * 1024 * 1024), 2)
        max_gb = round(self.max_storage_bytes / (1024 * 1024 * 1024), 2)
        percent = min(100.0, round((used_bytes / self.max_storage_bytes) * 100, 1)) if self.max_storage_bytes > 0 else 0

        # Count clips & locked files
        clips = list(self.recordings_dir.glob("*.mp4")) + list(self.recordings_dir.glob("*.mkv"))
        locked_count = sum(1 for c in clips if self.is_locked(c.name))

        return {
            "used_bytes": used_bytes,
            "max_bytes": self.max_storage_bytes,
            "used_mb": used_mb,
            "max_mb": max_mb,
            "used_gb": used_gb,
            "max_gb": max_gb,
            "percent_used": percent,
            "clip_count": len(clips),
            "locked_count": locked_count,
            "free_bytes": max(0, self.max_storage_bytes - used_bytes),
            "is_near_limit": used_bytes >= self.soft_limit_bytes
        }

    def is_locked(self, filename: str) -> bool:
        """Checks if a clip is locked/starred to prevent auto-cleanup."""
        clip_meta = self.metadata.get(filename, {})
        return clip_meta.get("locked", False)

    def set_locked(self, filename: str, locked: bool) -> bool:
        """Locks or unlocks a clip."""
        if filename not in self.metadata:
            self.metadata[filename] = {}
        self.metadata[filename]["locked"] = locked
        self._save_metadata()
        return locked

    def set_motion_flag(self, filename: str, motion_count: int, motion_timestamps: List[str] = None):
        """Records motion events detected during the clip."""
        if filename not in self.metadata:
            self.metadata[filename] = {}
        self.metadata[filename]["has_motion"] = motion_count > 0
        self.metadata[filename]["motion_events"] = motion_count
        if motion_timestamps:
            self.metadata[filename]["motion_timestamps"] = motion_timestamps[-20:]  # Store last 20
        self._save_metadata()

    def get_clip_meta(self, filename: str) -> Dict[str, Any]:
        """Gets metadata for a specific clip."""
        return self.metadata.get(filename, {})

    def cleanup_if_needed(self, active_filename: Optional[str] = None) -> Tuple[int, List[str]]:
        """
        FIFO Circular Buffer:
        Checks if total disk usage exceeds soft limit (e.g. 7.52 GB of 8.0 GB).
        If exceeded, deletes the oldest unlocked video clips and their thumbnails
        until total size drops below target purge size (e.g. 6.56 GB).
        Returns: (bytes_freed, list_of_deleted_filenames)
        """
        used_bytes = self.get_total_used_bytes()
        if used_bytes < self.soft_limit_bytes:
            return 0, []

        print(f"[StorageManager] Storage limit triggered ({used_bytes / (1024*1024):.1f} MB used). Initiating FIFO purge...")
        
        # Get all video files sorted by modification/creation time (oldest first)
        video_files = list(self.recordings_dir.glob("*.mp4")) + list(self.recordings_dir.glob("*.mkv"))
        video_files.sort(key=lambda p: p.stat().st_mtime)

        deleted_files: List[str] = []
        bytes_freed = 0

        for video_path in video_files:
            filename = video_path.name

            # Skip active in-progress recording file
            if active_filename and filename == active_filename:
                continue

            # Skip locked clips
            if self.is_locked(filename):
                print(f"[StorageManager] Skipping locked clip: {filename}")
                continue

            try:
                size = video_path.stat().st_size
                video_path.unlink(missing_ok=True)
                bytes_freed += size
                deleted_files.append(filename)

                # Delete corresponding thumbnail
                thumb_path = self.thumbnails_dir / f"{video_path.stem}.jpg"
                if thumb_path.exists():
                    bytes_freed += thumb_path.stat().st_size
                    thumb_path.unlink(missing_ok=True)

                # Remove from metadata
                if filename in self.metadata:
                    del self.metadata[filename]

                print(f"[StorageManager] Purged old clip: {filename} ({size / (1024*1024):.1f} MB)")

                # Check if we have freed enough space
                current_used = used_bytes - bytes_freed
                if current_used <= self.target_purge_bytes:
                    print(f"[StorageManager] Purge complete. Storage now at {current_used / (1024*1024):.1f} MB.")
                    break

            except Exception as e:
                print(f"[StorageManager] Error deleting {filename}: {e}")

        self._save_metadata()
        return bytes_freed, deleted_files

    def delete_clip(self, filename: str) -> bool:
        """Manually deletes a single clip, its thumbnail, and metadata."""
        video_path = self.recordings_dir / filename
        thumb_path = self.thumbnails_dir / f"{Path(filename).stem}.jpg"
        
        success = False
        if video_path.exists() and video_path.is_file():
            try:
                video_path.unlink()
                success = True
            except Exception as e:
                print(f"[StorageManager] Error deleting {filename}: {e}")

        if thumb_path.exists() and thumb_path.is_file():
            try:
                thumb_path.unlink()
            except Exception:
                pass

        if filename in self.metadata:
            del self.metadata[filename]
            self._save_metadata()

        return success
