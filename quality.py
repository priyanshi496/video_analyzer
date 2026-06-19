import logging
"""
quality.py — Per-second video quality analysis.

Computes blur (Laplacian variance) and motion (Farneback optical flow) on
downsampled frames for speed, then classifies motion into editor-friendly types.
Runs all videos in parallel via ThreadPoolExecutor.
"""

import cv2
cv2.ocl.setUseOpenCL(False)
cv2.setNumThreads(0)
import numpy as np
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from collections import Counter

from config import CONFIG


# ── Motion Type Classifier ────────────────────────────────────────────────────

def classify_motion_type(flow_x, flow_y, prev_flow_x, prev_flow_y,
                          blur_raw, shake_raw, shake_thresh, blur_thresh):
    """
    Classify each frame's motion into editor-meaningful categories:
      SETTLED        — camera barely moving; easiest to stabilize → PREFER
      LINEAR_FORWARD — predictable vertical walking bob → stabilizer can fix
      DISTANT_WIDE   — shaky but distant subject hides it → USABLE
      NORMAL         — within-norm motion → USABLE
      WHIP_PAN       — fast horizontal sweep → jello risk → AVOID
      CHAOTIC        — multi-directional random shake → hardest to salvage → AVOID
    """
    mag = np.sqrt(flow_x**2 + flow_y**2)
    mean_mag = float(np.mean(mag))
    mean_vx  = float(np.mean(flow_x))
    mean_vy  = float(np.mean(flow_y))

    horizontal_ratio = abs(mean_vx) / (abs(mean_vx) + abs(mean_vy) + 1e-6)
    vertical_ratio   = abs(mean_vy) / (abs(mean_vx) + abs(mean_vy) + 1e-6)

    flow_stack = np.stack([flow_x, flow_y], axis=-1)
    flat = flow_stack.reshape(-1, 2)
    if len(flat) > 0 and mean_mag > 0.5:
        norms = flat / (np.linalg.norm(flat, axis=1, keepdims=True) + 1e-6)
        consistency = float(
            np.mean(norms, axis=0) @ np.array([mean_vx, mean_vy]) / (mean_mag + 1e-6)
        )
    else:
        consistency = 0.0

    is_shaky  = shake_raw > shake_thresh
    is_blurry = blur_raw  < blur_thresh

    if mean_mag < 1.5:
        return "SETTLED"
    if is_shaky and horizontal_ratio > 0.7 and mean_mag > shake_thresh * 1.5:
        return "WHIP_PAN"
    if is_shaky and consistency < 0.3:
        return "CHAOTIC"
    if not is_shaky and vertical_ratio > 0.55:
        return "LINEAR_FORWARD"
    if is_shaky and blur_raw > blur_thresh * 1.2:
        return "DISTANT_WIDE"
    return "NORMAL"


# ── Single Video Quality Analysis ─────────────────────────────────────────────

def analyze_video_quality(video_path: str, sample_interval_sec: float = 0.5):
    """
    Sample every `sample_interval_sec` seconds.
    Frames are downsampled to CONFIG['quality_downsample_width'] px wide
    before optical flow computation — ~90% pixel reduction → 10-50x speedup.

    Returns:
        samples: list of per-sample dicts (t, blur_norm, shake_norm, motion_type, ...)
        stats:   dict of aggregated statistics and thresholds
    """
    is_image = Path(video_path).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    if is_image:
        samples = [{
            "t": 0.0,
            "blur_norm": 10.0,
            "shake_norm": 0.0,
            "is_shaky": False,
            "is_blurry": False,
            "motion_type": "SETTLED",
        }]
        stats = {
            "blur_mean": 10.0,
            "blur_std": 0.0,
            "blur_thresh": 5.0,
            "blur_thresh_norm": 5.0,
            "shake_mean": 0.0,
            "shake_std": 0.0,
            "shake_max": 0.0,
            "shake_thresh": 5.0,
            "shake_thresh_norm": 5.0,
            "duration": 3.0,
            "n_shaky_samples": 0,
            "n_blurry_samples": 0,
            "motion_counts": {"SETTLED": 1},
        }
        return samples, stats

    target_w = CONFIG["quality_downsample_width"]

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = total_frames / fps

    step = max(1, int(fps * sample_interval_sec))
    samples = []
    prev_gray   = None
    prev_flow_x = None
    prev_flow_y = None

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Only process every `step` frames (e.g. every 0.5 seconds)
        if frame_idx % step != 0:
            frame_idx += 1
            continue

        # ── DOWNSAMPLE for speed ──────────────────────────────────────────────
        h, w = frame.shape[:2]
        if w > target_w:
            target_h = int(h * target_w / w)
            frame = cv2.resize(frame, (target_w, target_h), interpolation=cv2.INTER_AREA)

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        blur_raw = cv2.Laplacian(gray, cv2.CV_64F).var()

        if prev_gray is not None:
            flow = cv2.calcOpticalFlowFarneback(
                prev_gray, gray, None,
                pyr_scale=0.5, levels=3, winsize=15,
                iterations=3, poly_n=5, poly_sigma=1.2, flags=0
            )
            flow_x    = flow[..., 0]
            flow_y    = flow[..., 1]
            shake_raw = float(np.mean(np.sqrt(flow_x**2 + flow_y**2)))
        else:
            flow_x    = np.zeros_like(gray, dtype=np.float32)
            flow_y    = np.zeros_like(gray, dtype=np.float32)
            shake_raw = 0.0

        samples.append({
            "t":         round(frame_idx / fps, 2),
            "blur_raw":  round(blur_raw,  2),
            "shake_raw": round(shake_raw, 2),
            "_flow_x":   flow_x,
            "_flow_y":   flow_y,
            "_pfx":      prev_flow_x,
            "_pfy":      prev_flow_y,
        })
        prev_gray   = gray
        prev_flow_x = flow_x
        prev_flow_y = flow_y
        frame_idx += 1

    cap.release()
    if not samples:
        return [], {}

    blur_vals  = np.array([s["blur_raw"]  for s in samples])
    shake_vals = np.array([s["shake_raw"] for s in samples])

    shake_mean, shake_std = float(shake_vals.mean()), float(shake_vals.std())
    shake_thresh = shake_mean + 1.0 * shake_std
    blur_mean, blur_std   = float(blur_vals.mean()),  float(blur_vals.std())
    blur_thresh  = max(blur_mean - 0.75 * blur_std, 0)

    max_blur  = float(blur_vals.max())  or 1.0
    max_shake = float(shake_vals.max()) or 1.0

    for s in samples:
        s["blur_norm"]   = round(s["blur_raw"]  / max_blur  * 10, 1)
        s["shake_norm"]  = round(s["shake_raw"] / max_shake * 10, 1)
        s["is_shaky"]    = s["shake_raw"] > shake_thresh
        s["is_blurry"]   = s["blur_raw"]  < blur_thresh
        s["motion_type"] = classify_motion_type(
            s["_flow_x"], s["_flow_y"],
            s["_pfx"] if s["_pfx"] is not None else s["_flow_x"],
            s["_pfy"] if s["_pfy"] is not None else s["_flow_y"],
            s["blur_raw"], s["shake_raw"], shake_thresh, blur_thresh
        )
        for k in ["_flow_x", "_flow_y", "_pfx", "_pfy"]:
            del s[k]

    shake_thresh_norm = round(shake_thresh / max_shake * 10, 1)
    blur_thresh_norm  = round(blur_thresh  / max_blur  * 10, 1)
    motion_counts     = dict(Counter(s["motion_type"] for s in samples))

    stats = {
        "blur_mean":         round(blur_mean,  2),
        "blur_std":          round(blur_std,   2),
        "blur_thresh":       round(blur_thresh, 2),
        "blur_thresh_norm":  blur_thresh_norm,
        "shake_mean":        round(shake_mean,  2),
        "shake_std":         round(shake_std,   2),
        "shake_max":         round(float(shake_vals.max()), 2),
        "shake_thresh":      round(shake_thresh, 2),
        "shake_thresh_norm": shake_thresh_norm,
        "duration":          round(duration, 2),
        "n_shaky_samples":   int(sum(1 for s in samples if s["is_shaky"])),
        "n_blurry_samples":  int(sum(1 for s in samples if s["is_blurry"])),
        "motion_counts":     motion_counts,
    }
    return samples, stats


# ── Parallel Quality Analysis for All Videos ──────────────────────────────────

def analyze_all_videos_quality(video_infos: list) -> dict:
    """
    Run analyze_video_quality for all videos in parallel threads.

    Returns:
        video_quality_map: {video_path: {"samples": [...], "stats": {...}}}
    """
    def _worker(info):
        path = info["path"]
        logging.info(f"  [quality] Analyzing {path} ...")
        samples, stats = analyze_video_quality(path)
        logging.info(f"  [quality] Done: {path}  "
              f"({stats.get('n_shaky_samples', 0)} shaky / "
              f"{stats.get('n_blurry_samples', 0)} blurry samples, "
              f"motion={stats.get('motion_counts', {})})")
        return path, samples, stats

    video_quality_map = {}
    with ThreadPoolExecutor(max_workers=len(video_infos) or 1) as ex:
        for path, samples, stats in ex.map(_worker, video_infos):
            video_quality_map[path] = {"samples": samples, "stats": stats}

    return video_quality_map
