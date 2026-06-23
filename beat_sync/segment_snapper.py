"""
beat_sync/segment_snapper.py
───────────────────────────────────────────────────────────────────────────────
Snaps the end_sec of each AI-generated segment to the nearest musical beat,
creating a reel where every cut lands precisely on the rhythm.

Algorithm per clip:
  1. Keep start_sec unchanged (AI narrative positioning stays intact).
  2. Find the beat_time CLOSEST to the original end_sec.
  3. Only snap if the nearest beat is within SNAP_TOLERANCE_SEC.
  4. Guarantee snapped duration >= MIN_CLIP_DURATION_SEC.
  5. If the BGM ends before the segment ends, no snap is applied.

This module has NO dependencies on the backend — it is fully standalone.
───────────────────────────────────────────────────────────────────────────────
"""

import copy
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional

from beat_sync.audio_analyzer import BeatMap

logger = logging.getLogger(__name__)


def snap_segments_to_beats(
    segments: List[Dict[str, Any]],
    beat_map: BeatMap,
    snap_tolerance_sec: float = 1.0,  # Increased to ensure we almost always find a beat
    min_clip_duration_sec: float = 0.5,
    fps: float = 30.0,
    verbose: bool = False,
    bgm_offset_sec: float = 0.0,
) -> List[Dict[str, Any]]:
    """
    Adjust each segment's end_sec so that the transition boundaries in the stitched 
    output video land precisely on the beats in the BeatMap.
    
    The start_sec of each segment is kept unchanged.
    """
    if not beat_map.beat_times:
        logger.warning("  [BeatSync] BeatMap has no beat times — snapping skipped.")
        return copy.deepcopy(segments)

    snapped = []
    beat_times = beat_map.beat_times
    total_snapped = 0
    total_skipped = 0

    # We track the cumulative playhead of the output video.
    # The first segment starts at output playhead 0.0.
    current_output_playhead = 0.0

    for i, seg in enumerate(segments):
        new_seg = dict(seg)
        
        # If the segment was already mapped to a specific beat window by the LLM,
        # we don't need to snap it again. Just pass it through.
        if new_seg.get("_beat_snapped", False):
            try:
                win_dur = float(new_seg.get("_beat_window_end", 0.0)) - float(new_seg.get("_beat_window_start", 0.0))
                current_output_playhead += max(0.0, win_dur)
            except:
                pass
            snapped.append(new_seg)
            if verbose:
                logger.info(f"  [Snap] Segment {i}: Already snapped to beat window {new_seg.get('_beat_window_start')} - {new_seg.get('_beat_window_end')}")
            continue

        if not new_seg.get("is_used", True):
            snapped.append(new_seg)
            continue

        try:
            start_sec = float(new_seg.get("start_sec", 0.0))
            end_sec   = float(new_seg.get("end_sec",   0.0))
        except (TypeError, ValueError):
            logger.warning(f"  [BeatSync] Segment {i}: invalid start/end_sec — skipping snap.")
            continue

        original_dur = end_sec - start_sec
        # The target unsnapped audio playhead if we don't snap this segment
        target_audio_playhead = bgm_offset_sec + current_output_playhead + original_dur

        # Calculate maximum allowed snapped playhead so we don't exceed the source video's end
        max_allowed_playhead = None
        video_path = seg.get("video_path")
        is_image = seg.get("is_image", False)
        
        # Ensure we have cv2 imported to read source video duration
        if not is_image and video_path and Path(video_path).exists():
            try:
                import cv2
                cap = cv2.VideoCapture(str(video_path))
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                if fps > 0 and frame_count > 0:
                    src_duration = frame_count / fps
                    max_allowed_playhead = current_output_playhead + (src_duration - start_sec)
                cap.release()
            except Exception as e:
                logger.debug(f"  [BeatSync] Could not read video duration for {video_path}: {e}")

        # Filter beat times to valid ones
        min_allowed_playhead = bgm_offset_sec + current_output_playhead + min_clip_duration_sec
        
        valid_beats = [b for b in beat_times if b >= min_allowed_playhead and b <= beat_map.total_duration_sec + 0.5]
        if max_allowed_playhead is not None:
            max_audio_playhead = bgm_offset_sec + max_allowed_playhead
            valid_beats = [b for b in valid_beats if b <= max_audio_playhead]

        best_beat = None
        if valid_beats:
            best_beat = min(valid_beats, key=lambda b: abs(b - target_audio_playhead))
            # Quantize the beat to the nearest frame boundary (at 30fps) to prevent FFmpeg fractional frame drift
            best_beat = round(best_beat * fps) / fps

        if best_beat is None:
            if verbose or True:
                logger.info(f"  [BeatSync] Seg {i:02d}: no valid beat found near target audio playhead {target_audio_playhead:.3f}s — keep original.")
            current_output_playhead += original_dur
            total_skipped += 1
            snapped.append(seg)
            continue

        distance = abs(best_beat - target_audio_playhead)

        if distance > snap_tolerance_sec and not is_image:
            if verbose or True:
                logger.info(
                    f"  [BeatSync] Seg {i:02d}: nearest beat {best_beat:.3f}s is {distance:.3f}s away "
                    f"(> tolerance {snap_tolerance_sec}s) — keep original duration {original_dur:.3f}s."
                )
            current_output_playhead += original_dur
            total_skipped += 1
            snapped.append(seg)
            continue

        # Snap output playhead to this beat
        snapped_dur = best_beat - (bgm_offset_sec + current_output_playhead)
        old_end = end_sec
        
        # Ensure snapped_dur is exactly a multiple of frames
        snapped_dur = round(snapped_dur * fps) / fps
        seg["end_sec"] = round(start_sec + snapped_dur, 4)
        seg["_beat_snapped"] = True
        seg["_beat_snap_distance_sec"] = round(distance, 4)
        
        direction = "▶ extended" if best_beat > target_audio_playhead else "◀ shortened"
        logger.info(
            f"  [BeatSync] Seg {i:02d} [{start_sec:.2f}s→{old_end:.2f}s (dur={original_dur:.2f}s)] "
            f"{direction} to snapped dur {snapped_dur:.2f}s (audio cut @ {best_beat:.3f}s, Δ={distance:.3f}s)"
        )
        
        current_output_playhead += snapped_dur
        total_snapped += 1
        snapped.append(seg)

    logger.info(
        f"  [BeatSync] Snapping complete: "
        f"{total_snapped} clip(s) snapped to beat, {total_skipped} kept original."
    )
    return snapped


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    import json
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))

    from beat_sync.audio_analyzer import analyze_bgm
    from beat_sync.config import BGM_PATH, SNAP_TOLERANCE_SEC, MIN_CLIP_DURATION_SEC, VERBOSE_LOGGING

    # Example segments to test with
    test_segments = [
        {"start_sec": 0.0,  "end_sec": 3.2,  "is_used": True, "video_path": "test.mp4"},
        {"start_sec": 3.2,  "end_sec": 6.8,  "is_used": True, "video_path": "test.mp4"},
        {"start_sec": 6.8,  "end_sec": 10.1, "is_used": True, "video_path": "test.mp4"},
        {"start_sec": 10.1, "end_sec": 14.5, "is_used": True, "video_path": "test.mp4"},
        {"start_sec": 14.5, "end_sec": 18.0, "is_used": True, "video_path": "test.mp4"},
    ]

    print(f"\nLoading beat map from: {BGM_PATH}")
    bm = analyze_bgm(BGM_PATH, verbose=VERBOSE_LOGGING)
    print(f"{bm}\n")

    print("Snapping segments...")
    result = snap_segments_to_beats(
        test_segments, bm,
        snap_tolerance_sec=SNAP_TOLERANCE_SEC,
        min_clip_duration_sec=MIN_CLIP_DURATION_SEC,
        verbose=True,
    )

    print("\nResult:")
    for seg in result:
        snapped = "✓ SNAPPED" if seg.get("_beat_snapped") else "  kept"
        print(f"  {snapped}  {seg['start_sec']:.3f}s → {seg['end_sec']:.3f}s (dur={(seg['end_sec'] - seg['start_sec']):.3f}s)")
