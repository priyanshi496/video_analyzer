import logging
"""
frames.py — Extract representative frames from a video window.

Also checks for black frames by computing mean pixel brightness on
already-extracted frames (zero extra I/O cost).
"""

import cv2
import numpy as np
from pathlib import Path

FRAMES_DIR = Path("timeline_frames")
FRAMES_DIR.mkdir(exist_ok=True)

def pick_frame_count(duration_sec: float) -> int:
    # Dynamically extract ~1 frame per 10 seconds of video (minimum 2 frames)
    count = round(duration_sec / 10.0)
    return max(2, count)


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
    from app.services.logger_service import _get_run_id
    run_id = _get_run_id()
    if run_id and run_id != "unknown_job":
        run_frames_dir = FRAMES_DIR / run_id
    else:
        run_frames_dir = FRAMES_DIR
    run_frames_dir.mkdir(exist_ok=True, parents=True)

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
        out_path = run_frames_dir / f"{stem}_t00_0.00.jpg"
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

        out_path = run_frames_dir / f"{stem}_t{i:02d}_{ts_in_window:.2f}.jpg"
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
    threshold = 20
    avg = sum(f.get("mean_brightness", 255) for f in frame_meta) / len(frame_meta)
    return avg < threshold


def extract_thumbnail(video_path: str, output_dir: str, max_size: int = 768) -> str:
    """
    Extracts a single representative thumbnail for a video or image.
    For videos, it seeks to t=1.0s (or t=0.5s if too short).
    For images, it just resizes and saves it.
    Returns the absolute path to the extracted JPEG.
    """
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = Path(video_path).stem
    out_path = out_dir / f"{stem}_thumb.jpg"
    
    is_image = Path(video_path).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    
    if is_image:
        frame = cv2.imread(video_path)
        if frame is None:
            logging.warning(f"  ✗ Could not read image for thumbnail: {video_path}")
            return ""
    else:
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            logging.warning(f"  ✗ Could not open video for thumbnail: {video_path}")
            return ""
        
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = total_frames / fps if fps > 0 else 0
        
        target_sec = 1.0 if duration > 1.0 else (duration / 2.0)
        frame_idx = min(int(target_sec * fps), total_frames - 1)
        
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        cap.release()
        
        if not ret or frame is None:
            logging.warning(f"  ✗ Could not read frame at {target_sec}s for thumbnail: {video_path}")
            return ""

    h, w = frame.shape[:2]
    if max(h, w) > max_size:
        scale = max_size / max(h, w)
        frame = cv2.resize(frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

    success = cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not success:
        logging.error(f"  ✗ Failed to write thumbnail to {out_path}!")
        return ""
        
    return str(out_path.absolute())
