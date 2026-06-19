"""
beat_sync/__init__.py
───────────────────────────────────────────────────────────────────────────────
Public API for the beat_sync module.

The backend calls ONE function: apply_beat_sync()

If anything inside fails (missing music file, librosa not installed, FFmpeg
error, etc.) — it catches the exception and returns the ORIGINAL video path
unchanged. The pipeline never crashes because of beat sync.
───────────────────────────────────────────────────────────────────────────────
"""

import logging
from pathlib import Path
from typing import List, Dict, Any, Tuple

logger = logging.getLogger(__name__)

__version__ = "1.0.0"
__all__ = ["apply_beat_sync"]


def apply_beat_sync(
    segments: List[Dict[str, Any]],
    video_path: str,
    output_path: str,
) -> Tuple[List[Dict[str, Any]], str]:
    """
    Apply beat-syncing to the final stitched reel.

    Pipeline:
      1. Load BGM path from beat_sync/config.py
      2. Analyze beat timestamps using librosa
      3. Snap each segment's end_sec to the nearest beat
      4. Mix the BGM into the stitched video using FFmpeg
      5. Return (snapped_segments, output_video_path)

    This function NEVER raises — if anything goes wrong, it returns the
    original segments and video path unchanged (safe fallback mode).

    Args:
        segments    : List of best_segment dicts from the pipeline
                      (each has 'start_sec', 'end_sec', 'is_used', etc.)
        video_path  : Path to the stitched reel produced by build_reel_from_segments()
        output_path : Where to write the beat-synced output video

    Returns:
        (segments, video_path) — either beat-synced or original (on failure)
    """
    try:
        # Import config from within the package
        from beat_sync.config import (
            BGM_PATH,
            BGM_VOLUME,
            REPLACE_ORIGINAL_AUDIO,
            ORIGINAL_AUDIO_VOLUME,
            SNAP_TOLERANCE_SEC,
            MIN_CLIP_DURATION_SEC,
            VERBOSE_LOGGING,
        )
    except Exception as e:
        logger.warning(f"  [BeatSync] Could not load config: {e} — skipping beat sync.")
        return segments, video_path

    # ── Step 1: Check BGM file exists before doing any work ──────────────────
    bgm_path = Path(BGM_PATH)
    if not bgm_path.exists():
        logger.warning(
            f"  [BeatSync] BGM file not found: {BGM_PATH}\n"
            f"  → Drop your music into beat_sync/music/ and update BGM_PATH in beat_sync/config.py\n"
            f"  → Beat sync SKIPPED — original video used."
        )
        return segments, video_path

    # ── Step 2: Analyze beats ─────────────────────────────────────────────────
    try:
        from beat_sync.audio_analyzer import analyze_bgm
        beat_map = analyze_bgm(str(bgm_path), verbose=VERBOSE_LOGGING)
    except ImportError as e:
        logger.warning(
            f"  [BeatSync] librosa not installed: {e}\n"
            f"  → Run: pip install -r beat_sync/requirements.txt\n"
            f"  → Beat sync SKIPPED — original video used."
        )
        return segments, video_path
    except Exception as e:
        logger.warning(f"  [BeatSync] Beat analysis failed: {e} — skipping beat sync.")
        return segments, video_path

    # ── Step 3: Snap segment durations to beats ───────────────────────────────
    try:
        from beat_sync.segment_snapper import snap_segments_to_beats
        snapped_segments = snap_segments_to_beats(
            segments=segments,
            beat_map=beat_map,
            snap_tolerance_sec=SNAP_TOLERANCE_SEC,
            min_clip_duration_sec=MIN_CLIP_DURATION_SEC,
            verbose=VERBOSE_LOGGING,
        )
    except Exception as e:
        logger.warning(f"  [BeatSync] Segment snapping failed: {e} — using original segments.")
        snapped_segments = segments  # fallback: keep original segments

    # ── Step 4: Mix BGM into the video ───────────────────────────────────────
    try:
        from beat_sync.audio_mixer import mix_bgm_into_video
        final_video_path = mix_bgm_into_video(
            video_path=video_path,
            bgm_path=str(bgm_path),
            output_path=output_path,
            bgm_volume=BGM_VOLUME,
            replace_original_audio=REPLACE_ORIGINAL_AUDIO,
            original_audio_volume=ORIGINAL_AUDIO_VOLUME,
        )
    except Exception as e:
        logger.warning(
            f"  [BeatSync] Audio mixing failed: {e}\n"
            f"  → Falling back to original video without music."
        )
        return snapped_segments, video_path  # return snapped segs but original video

    logger.info(
        f"  [BeatSync] ✅ Beat sync complete! "
        f"BPM={beat_map.tempo_bpm:.1f} | "
        f"Beats={len(beat_map.beat_times)} | "
        f"Output: {Path(final_video_path).name}"
    )

    return snapped_segments, final_video_path
