"""
beat_sync/audio_mixer.py
───────────────────────────────────────────────────────────────────────────────
Uses FFmpeg to bake the background music (BGM) track into the final stitched
video. Supports two modes:

  REPLACE_ORIGINAL_AUDIO = True  →  BGM replaces all original clip audio
  REPLACE_ORIGINAL_AUDIO = False →  BGM is mixed with original audio (BGM dominant)

This module has NO dependencies on the backend — it is fully standalone.
Requires FFmpeg to be available in PATH.
───────────────────────────────────────────────────────────────────────────────
"""

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def mix_bgm_into_video(
    video_path: str,
    bgm_path: str,
    output_path: str,
    bgm_volume: float = 0.85,
    replace_original_audio: bool = True,
    original_audio_volume: float = 0.15,
    bgm_start_sec: float = 0.0,
) -> str:
    """
    Overlay background music onto the final stitched video using FFmpeg.

    Args:
        video_path             : Path to the input video (the stitched reel)
        bgm_path               : Path to the BGM audio file
        output_path            : Path for the output video with music baked in
        bgm_volume             : BGM volume (0.0–1.0)
        replace_original_audio : If True, mutes original audio and uses only BGM.
                                 If False, mixes BGM over existing audio.
        original_audio_volume  : Original audio volume when mixing (only for False mode)
        bgm_start_sec          : Start offset in the BGM file to align the video to a hook

    Returns:
        output_path (str) — path to the finished video

    Raises:
        FileNotFoundError : If video or BGM file does not exist
        RuntimeError      : If FFmpeg command fails
    """
    vp = Path(video_path)
    bp = Path(bgm_path)
    op = Path(output_path)

    if not vp.exists():
        raise FileNotFoundError(f"[BeatSync] Input video not found: {video_path}")
    if not bp.exists():
        raise FileNotFoundError(
            f"[BeatSync] BGM file not found: {bgm_path}\n"
            f"  → Update BGM_PATH in beat_sync/config.py and drop your music into beat_sync/music/"
        )

    op.parent.mkdir(parents=True, exist_ok=True)

    if replace_original_audio:
        cmd = _build_replace_cmd(vp, bp, op, bgm_volume, bgm_start_sec)
        mode_label = "REPLACE (BGM only)"
    else:
        cmd = _build_mix_cmd(vp, bp, op, bgm_volume, original_audio_volume, bgm_start_sec)
        mode_label = f"MIX (BGM {bgm_volume:.0%} + orig {original_audio_volume:.0%})"

    logger.info(f"  [BeatSync] Mixing audio ({mode_label}) → {op.name} ...")
    logger.debug(f"  [BeatSync] FFmpeg cmd: {' '.join(cmd)}")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error(f"  [BeatSync] FFmpeg failed:\n{result.stderr[-800:]}")
        raise RuntimeError(
            f"[BeatSync] FFmpeg audio mix failed:\n{result.stderr[-400:]}"
        )

    size_mb = op.stat().st_size / 1_000_000
    logger.info(f"  [BeatSync] ✓ Audio mix complete: {op.name} ({size_mb:.1f} MB)")
    return str(op)


def _build_replace_cmd(
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    bgm_volume: float,
    bgm_start_sec: float = 0.0,
) -> list:
    """
    FFmpeg command: discard original audio, use BGM only.
    Loops the BGM if shorter than the video; trims at video length.

    Strategy:
      -map 0:v        → video stream from input video
      -map 1:a        → audio stream from BGM file
      -shortest       → stop when the shorter input ends (prevents blank audio tail)
      -af volume=X    → apply BGM volume
      -c:v copy       → no video re-encode (fast)
      -c:a aac        → encode audio to AAC for compatibility
    """
    return [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", str(bgm_start_sec),
        "-stream_loop", "-1",   # loop BGM indefinitely so it covers any video length
        "-i", str(bgm_path),
        "-map", "0:v",
        "-map", "1:a",
        "-af", f"volume={bgm_volume:.4f}",
        "-shortest",
        "-c:v", "copy",
        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        str(output_path),
    ]


def _build_mix_cmd(
    video_path: Path,
    bgm_path: Path,
    output_path: Path,
    bgm_volume: float,
    original_audio_volume: float,
    bgm_start_sec: float = 0.0,
) -> list:
    """
    FFmpeg command: mix BGM on top of original audio.
    Original audio is kept but ducked (lowered in volume).

    filter_complex:
      [0:a] volume={orig_vol} [orig]
      [1:a] volume={bgm_vol}  [bgm]
      [orig][bgm] amix=inputs=2:duration=first [aout]

    duration=first → output stops at video length (never extends to BGM length)
    """
    filter_complex = (
        f"[0:a]volume={original_audio_volume:.4f}[orig];"
        f"[1:a]volume={bgm_volume:.4f}[bgm];"
        f"[orig][bgm]amix=inputs=2:duration=first[aout]"
    )
    return [
        "ffmpeg", "-y",
        "-i", str(video_path),
        "-ss", str(bgm_start_sec),
        "-stream_loop", "-1",   # loop BGM
        "-i", str(bgm_path),
        "-filter_complex", filter_complex,
        "-map", "0:v",
        "-map", "[aout]",
        "-shortest",
        "-c:v", "copy",
        "-c:a", "aac",
        "-ar", "44100",
        "-ac", "2",
        "-movflags", "+faststart",
        str(output_path),
    ]


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if len(sys.argv) < 3:
        print("Usage: python audio_mixer.py <video.mp4> <music.mp3> [output.mp4]")
        sys.exit(1)

    in_video = sys.argv[1]
    in_bgm   = sys.argv[2]
    out_path = sys.argv[3] if len(sys.argv) > 3 else "output_beat_synced.mp4"

    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from beat_sync.config import BGM_VOLUME, REPLACE_ORIGINAL_AUDIO, ORIGINAL_AUDIO_VOLUME

    result = mix_bgm_into_video(
        video_path=in_video,
        bgm_path=in_bgm,
        output_path=out_path,
        bgm_volume=BGM_VOLUME,
        replace_original_audio=REPLACE_ORIGINAL_AUDIO,
        original_audio_volume=ORIGINAL_AUDIO_VOLUME,
    )
    print(f"\n✓ Done: {result}")
