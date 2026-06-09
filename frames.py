import logging
"""
frames.py — Extract representative frames from a video window.

Also checks for black frames by computing mean pixel brightness on
already-extracted frames (zero extra I/O cost).
"""

import cv2
import numpy as np
from pathlib import Path

from config import CONFIG

FRAMES_DIR = Path("timeline_frames")
FRAMES_DIR.mkdir(exist_ok=True)


def pick_frame_count(duration_sec: float) -> int:
    af = CONFIG["adaptive_frames"]
    if duration_sec < 15:
        return af["short"]
    elif duration_sec < 45:
        return af["medium"]
    else:
        return af["long"]


def extract_representative_frames(
    video_path: str,
    duration_sec: float,
    frames_per_video: int,
    offset_sec: float = 0.0,
    chunk_label: str = "",
    max_size: int = 768,
) -> list:
    """
    Extract evenly-spaced frames from a time window.

    Each returned dict includes:
        frame_index, timestamp_sec, abs_timestamp, path,
        mean_brightness  ← used by the UI to flag near-black clips
    """
    FRAMES_DIR.mkdir(exist_ok=True, parents=True)
    is_image = Path(video_path).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    if is_image:
        frame = cv2.imread(video_path)
        if frame is None:
            logging.info(f"  ✗ Could not read image {video_path}")
            return []
        
        stem = Path(video_path).stem + (f"_{chunk_label}" if chunk_label else "")
        h, w = frame.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        mean_brightness = float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))
        out_path = FRAMES_DIR / f"{stem}_t00_0.00.jpg"
        success = cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not success:
            logging.error(f"  ✗ Failed to write static image frame to {out_path}!")
            return []

        return [{
            "frame_index":    0,
            "timestamp_sec":  0.0,
            "abs_timestamp":  0.0,
            "path":           str(out_path),
            "mean_brightness": round(mean_brightness, 1),
        }]

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stem = Path(video_path).stem + (f"_{chunk_label}" if chunk_label else "")

    positions = (
        [0.5]
        if frames_per_video == 1
        else [(i + 0.5) / frames_per_video for i in range(frames_per_video)]
    )

    saved = []
    for i, p in enumerate(positions):
        ts_in_window = min(duration_sec * p, max(duration_sec - 0.05, 0))
        ts_in_file   = offset_sec + ts_in_window
        frame_idx    = min(max(int(ts_in_file * fps), 0), max(total_frames - 1, 0))
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            logging.info(f"  ⚠️  Could not read frame {i} at {ts_in_file:.2f}s from {video_path}")
            continue

        # Resize for LLM payload efficiency
        h, w = frame.shape[:2]
        if max(h, w) > max_size:
            scale = max_size / max(h, w)
            frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        # Compute mean brightness (used for black-frame warning in UI)
        mean_brightness = float(np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)))

        out_path = FRAMES_DIR / f"{stem}_t{i:02d}_{ts_in_window:.2f}.jpg"
        success = cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not success:
            logging.error(f"  ✗ Failed to write video frame to {out_path}!")
            continue

        saved.append({
            "frame_index":    i,
            "timestamp_sec":  round(ts_in_window, 2),
            "abs_timestamp":  round(ts_in_file,   2),
            "path":           str(out_path),
            "mean_brightness": round(mean_brightness, 1),
        })

    cap.release()

    if not saved:
        logging.info(f"  ✗ No frames extracted from {video_path} "
              f"(offset={offset_sec}s, dur={duration_sec}s)")
    return saved


def is_likely_black_clip(frame_meta: list) -> bool:
    """
    Return True if the mean brightness across all extracted frames is below threshold.
    Uses already-extracted frames — no extra video I/O.
    """
    if not frame_meta:
        return False
    threshold = CONFIG["black_frame_brightness_threshold"]
    avg = sum(f.get("mean_brightness", 255) for f in frame_meta) / len(frame_meta)
    return avg < threshold
