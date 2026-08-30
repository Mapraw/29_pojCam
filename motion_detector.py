import cv2
import time
import numpy as np
from datetime import datetime
from typing import List, Tuple

class MotionDetector:
    def __init__(self, min_area=800, threshold_val=25, cooldown_seconds=3.0):
        self.min_area = min_area
        self.threshold_val = threshold_val
        self.cooldown_seconds = cooldown_seconds
        
        self.bg_subtractor = cv2.createBackgroundSubtractorMOG2(history=300, varThreshold=36, detectShadows=False)
        self.last_motion_time = 0
        self.motion_events: List[str] = []
        self.total_motion_count = 0

    def reset_segment(self):
        """Resets motion counters for a new 15-minute video segment."""
        events = list(self.motion_events)
        count = self.total_motion_count
        self.motion_events = []
        self.total_motion_count = 0
        return count, events

    def process_frame(self, frame: np.ndarray) -> bool:
        """
        Processes a downscaled frame to detect motion with minimal CPU.
        Returns True if motion was detected in this frame.
        """
        if frame is None:
            return False

        try:
            # Downscale frame to 320x180 for lightning-fast Pi processing (< 1ms per frame)
            small = cv2.resize(frame, (320, 180), interpolation=cv2.INTER_NEAREST)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            blurred = cv2.GaussianBlur(gray, (15, 15), 0)

            # Apply background subtraction
            fg_mask = self.bg_subtractor.apply(blurred)
            _, thresh = cv2.threshold(fg_mask, self.threshold_val, 255, cv2.THRESH_BINARY)
            
            # Dilate to fill holes
            dilated = cv2.dilate(thresh, None, iterations=2)
            contours, _ = cv2.findContours(dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

            motion_in_frame = False
            for contour in contours:
                if cv2.contourArea(contour) >= self.min_area:
                    motion_in_frame = True
                    break

            now = time.time()
            if motion_in_frame:
                if (now - self.last_motion_time) > self.cooldown_seconds:
                    self.last_motion_time = now
                    self.total_motion_count += 1
                    timestamp_str = datetime.now().strftime("%H:%M:%S")
                    self.motion_events.append(timestamp_str)
                    return True

            return False
        except Exception:
            return False
