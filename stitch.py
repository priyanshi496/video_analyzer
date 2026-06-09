import logging
"""
stitch.py — FFmpeg trim, re-encode, and concatenate clips into a final reel.

Fixes applied vs original notebook:
  - -pix_fmt yuv420p enforced on every clip (prevents black frames at transitions)
  - -fflags +genpts -async 1 in concat command (fixes audio/video timeline drift)
"""

import subprocess
import shutil
import zipfile
from pathlib import Path


def get_video_duration(video_path: str) -> float:
    """Uses ffprobe to extract video duration, with cv2 fallback."""
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            return float(res.stdout.strip())
        except ValueError:
            pass
    # Fallback to OpenCV
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps > 0 and frame_count > 0:
        return frame_count / fps
    raise ValueError(f"Could not read video duration for: {video_path}")


def trim_and_normalize_clip(
    video_path: str,
    start_sec: float,
    end_sec: float,
    out_path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    rotation: int = 0,
) -> str:
    path_obj = Path(video_path)
    if not path_obj.exists():
        raise FileNotFoundError(f"Source file does not exist: {video_path}")

    is_image = path_obj.suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")

    if not is_image:
        try:
            duration = get_video_duration(str(path_obj))
            # Clamp boundaries
            start_sec = max(0.0, float(start_sec))
            end_sec = min(duration, float(end_sec))
        except Exception as e:
            logging.warning(f"Failed to probe duration for {video_path}: {e}. Skipping boundary clamping.")
            start_sec = float(start_sec)
            end_sec = float(end_sec)
    else:
        start_sec = float(start_sec)
        end_sec = float(end_sec)

    dur = end_sec - start_sec
    if dur < 0.1:
        raise ValueError(f"Invalid duration {dur:.2f}s (start={start_sec:.2f}s, end={end_sec:.2f}s). Must be at least 0.1s.")
    if start_sec >= end_sec:
        raise ValueError(f"Reversed range: start_sec ({start_sec:.2f}s) >= end_sec ({end_sec:.2f}s).")

    transpose_filter = ""
    if rotation == 90:
        transpose_filter = "transpose=1,"
    elif rotation == 180:
        transpose_filter = "transpose=1,transpose=1,"
    elif rotation == 270:
        transpose_filter = "transpose=2,"

    if is_image:
        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-i", str(video_path),
            "-f", "lavfi",
            "-i", "anullsrc=r=44100:cl=stereo",
            "-t", f"{dur:.3f}",
            "-vf", (
                f"{transpose_filter}"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={fps}"
            ),
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-shortest",
            "-movflags", "+faststart",
            str(out_path),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-ss", f"{start_sec:.3f}",
            "-i", str(video_path),
            "-t", f"{dur:.3f}",
            "-vf", (
                f"{transpose_filter}"
                f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                f"fps={fps}"
            ),
            "-pix_fmt", "yuv420p",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-ar", "44100",
            "-ac", "2",
            "-movflags", "+faststart",
            "-avoid_negative_ts", "make_zero",
            str(out_path),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logging.error(f"FFmpeg command failed: {' '.join(cmd)}")
        logging.error(f"FFmpeg stderr output:\n{result.stderr}")
        raise RuntimeError(f"ffmpeg trim/normalize failed:\n{result.stderr}")
    return str(out_path)


def stitch_clips(
    clip_paths: list,
    output_path,
) -> str:
    """
    Concatenate pre-normalized clips into one final reel.
    Returns the path to the finished reel.
    """
    if not clip_paths:
        raise RuntimeError("No clips available to stitch.")

    concat_list = Path("concat_list.txt")
    with open(concat_list, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f",      "concat",
        "-safe",   "0",
        "-i",      str(concat_list),
        "-fflags", "+genpts",     # ← regenerate PTS to align audio/video at clip boundaries
        "-af",     "aresample=async=1", # ← modern filter to squash audio drift
        "-c:v",    "copy",
        "-c:a",    "aac",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_list.unlink(missing_ok=True)

    if result.returncode != 0:
        # Partial recovery: save individual clips as zip
        zip_path = Path("highlight_clips_partial.zip")
        logging.info(f"\n✗ Concat failed: {result.stderr[:400]}")
        logging.info(f"  → Saving {len(clip_paths)} clip(s) to {zip_path}...")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for p in clip_paths:
                zf.write(p, Path(p).name)
        raise RuntimeError(f"Concat failed — clips saved to {zip_path}")

    return str(output_path)


def build_reel_from_segments(
    best_segments: list,
    clips_dir: Path,
    reel_path: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
) -> str:
    """
    High-level helper: trim all segments → re-encode → stitch → return reel path.
    Used by both main.py and the Flask editor when the user clicks "Rebuild Reel".
    """
    # Filter only used segments (default to True if key is not present)
    used_segments = sorted(
        [s for s in best_segments if s.get("is_used", True)],
        key=lambda x: x.get("story_position", 9999)
    )

    # Auto-detect aspect ratio if defaults are requested
    if width == 1080 and height == 1920:
        landscape_count = 0
        portrait_count = 0
        import cv2
        for seg in used_segments:
            video_path = seg.get("video_path")
            if not video_path:
                continue
            try:
                is_image = Path(video_path).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
                if is_image:
                    img = cv2.imread(video_path)
                    if img is not None:
                        h, w = img.shape[:2]
                        if w >= h:
                            landscape_count += 1
                        else:
                            portrait_count += 1
                else:
                    cap = cv2.VideoCapture(video_path)
                    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()
                    if w > 0 and h > 0:
                        if w >= h:
                            landscape_count += 1
                        else:
                            portrait_count += 1
            except Exception:
                pass

        if landscape_count >= portrait_count and landscape_count > 0:
            width, height = 1920, 1080
            logging.info(f"  📺 Detected landscape preference ({landscape_count} vs {portrait_count}). Output resolution set to 1920x1080.")
        else:
            width, height = 1080, 1920
            logging.info(f"  📱 Detected portrait preference ({portrait_count} vs {landscape_count}). Output resolution set to 1080x1920.")

    if clips_dir.exists():
        import shutil
        shutil.rmtree(clips_dir)
    clips_dir.mkdir(exist_ok=True)
    ordered_clip_paths = []
    trim_failures      = []

    logging.info(f"\nTrimming {len(used_segments)} clip(s)...")
    for position, seg in enumerate(used_segments):
        role      = seg.get("story_role", seg.get("narrative_role", "clip"))
        src_stem  = Path(seg["video_path"]).stem   # e.g. "jiya5"
        out_path  = clips_dir / f"clip_{position:02d}_{role}_{src_stem}.mp4"
        try:
            rot = seg.get("camera_rotation", 0)
            trim_and_normalize_clip(seg["video_path"], seg["start_sec"], seg["end_sec"], out_path, width, height, fps, rot)
            ordered_clip_paths.append(str(out_path))
            logging.info(f"  [{position}] {role:8s} → {out_path.name}  "
                  f"({seg['start_sec']}s–{seg['end_sec']}s from {Path(seg['video_path']).name})")
        except Exception as e:
            logging.info(f"  [{position}] ✗ Trim failed: {e}")
            fallback = clips_dir / f"clip_{position:02d}_{role}_{src_stem}_FULL_FALLBACK.mp4"
            try:
                shutil.copy(seg["video_path"], str(fallback))
                ordered_clip_paths.append(str(fallback))
                trim_failures.append(position)
                logging.info(f"       → Fallback: full source copied as {fallback.name}")
            except Exception as e2:
                logging.info(f"       → Fallback copy also failed: {e2} — clip {position} dropped.")

    if trim_failures:
        logging.info(f"⚠️  {len(trim_failures)} clip(s) used full-source fallback.")

    if len(ordered_clip_paths) == 0:
        raise RuntimeError("No clips available to stitch.")

    if len(ordered_clip_paths) == 1:
        logging.info("Only 1 clip — skipping stitch, copying directly.")
        shutil.copy(ordered_clip_paths[0], str(reel_path))
    else:
        logging.info(f"\nStitching {len(ordered_clip_paths)} clips → {reel_path} ({width}×{height} @ {fps}fps)...")
        stitch_clips(ordered_clip_paths, reel_path)

    size_mb = reel_path.stat().st_size / 1_000_000
    logging.info(f"✓ Reel saved: {reel_path}  ({size_mb:.1f} MB)")
    return str(reel_path)
