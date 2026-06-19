import logging
import subprocess
import shutil
import zipfile
import json
from pathlib import Path

logger = logging.getLogger(__name__)


def get_video_duration(video_path: str) -> float:
    """Uses OpenCV to mathematically compute exact video frame duration, with ffprobe fallback."""
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    
    # If OpenCV successfully calculates a valid duration, use it.
    # This guarantees exact frame alignment for xfade transitions.
    if fps > 0 and frame_count > 0:
        return float(frame_count) / float(fps)
        
    # Fallback to FFprobe metadata container duration
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode == 0:
        try:
            return float(res.stdout.strip())
        except ValueError:
            pass

    raise ValueError(f"Could not read video duration for: {video_path}")


def has_audio_stream(video_path: str) -> bool:
    """Uses ffprobe to detect if the video has an audio stream."""
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        return "audio" in res.stdout
    except Exception:
        return False


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
            logger.warning(f"Failed to probe duration for {video_path}: {e}. Skipping boundary clamping.")
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
        has_audio = False
        try:
            has_audio = has_audio_stream(str(video_path))
        except Exception as e:
            logger.warning(f"Failed to check audio stream for {video_path}: {e}")

        if not has_audio:
            # Video input but no audio stream — synthesize a silent track
            cmd = [
                "ffmpeg", "-y",
                "-ss", f"{start_sec:.3f}",
                "-i", str(video_path),
                "-f", "lavfi",
                "-i", "anullsrc=r=44100:cl=stereo",
                # -t placed here as an OUTPUT option, correctly limiting encoded duration
                "-t", f"{dur:.3f}",
                "-vf", (
                    f"{transpose_filter}"
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=black,"
                    f"fps={fps}"
                ),
                "-pix_fmt", "yuv420p",
                "-map", "0:v:0",
                "-map", "1:a:0",
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
        logger.error(f"FFmpeg command failed: {' '.join(cmd)}")
        logger.error(f"FFmpeg stderr output:\n{result.stderr}")
        raise RuntimeError(f"ffmpeg trim/normalize failed:\n{result.stderr}")
    return str(out_path)


def _stitch_concat_demuxer(clip_paths: list, output_path) -> str:
    """Helper to perform fast concat demuxer stitch (hard cuts only)."""
    import uuid
    concat_list = Path(output_path).parent / f"concat_list_{uuid.uuid4().hex}.txt"
    with open(concat_list, "w") as f:
        for p in clip_paths:
            f.write(f"file '{p}'\n")

    cmd = [
        "ffmpeg", "-y",
        "-f",      "concat",
        "-safe",   "0",
        "-i",      str(concat_list),
        "-fflags", "+genpts",
        "-af",     "aresample=async=1",
        "-c:v",    "copy",
        "-c:a",    "aac",
        str(output_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    concat_list.unlink(missing_ok=True)

    if result.returncode != 0:
        # Partial recovery: save individual clips as zip
        zip_path = Path(output_path).parent / "highlight_clips_partial.zip"
        logger.info(f"\n✗ Concat failed: {result.stderr[:400]}")
        logger.info(f"  → Saving {len(clip_paths)} clip(s) to {zip_path}...")
        with zipfile.ZipFile(zip_path, "w") as zf:
            for p in clip_paths:
                zf.write(p, Path(p).name)
        raise RuntimeError(f"Concat failed — clips saved to {zip_path}")

    return str(output_path)


def stitch_clips(
    clip_paths: list,
    output_path,
    transitions: list = None,
    transition_durations: list = None,
) -> str:
    """
    Concatenate pre-normalized clips into one final reel.
    If transitions are provided, uses xfade/acrossfade complex filter graph.
    Falls back to safe concat demuxer on error or if no transitions are requested.
    """
    if not clip_paths:
        raise RuntimeError("No clips available to stitch.")

    # 1. Determine if we should use transitions
    use_transitions = False
    if transitions:
        for t in transitions:
            if t and t != "cut":
                use_transitions = True
                break

    if not use_transitions:
        return _stitch_concat_demuxer(clip_paths, output_path)

    # 2. Render with transitions
    try:
        logger.info(f"Rendering {len(clip_paths)} clips with xfade transitions...")
        durations = []
        for p in clip_paths:
            durations.append(get_video_duration(p))

        n = len(clip_paths)
        t_types = []
        t_durs = []
        
        # Map narrative rules/UI tags to actual FFmpeg xfade transition filters
        TRANSITION_MAP = {
            "fade": "fade",
            "dissolve": "dissolve",
            "zoom_in": "zoomin",
            "zoom_out": "fade",
            "zoom_dissolve": "zoomin",
            "wipe_left": "wipeleft",
            "wipe_right": "wiperight",
            "slide_left": "slideleft",
            "slide_right": "slideright",
            "circle_crop": "circlecrop",
            "circleopen": "circleopen",
            "circleclose": "circleclose",
            "cut": "fade",
        }

        for i in range(n - 1):
            t_type = transitions[i] if i < len(transitions) else "cut"
            t_dur = transition_durations[i] if (transition_durations and i < len(transition_durations)) else 0.5
            
            if t_type == "cut":
                mapped_type = "fade"
                mapped_dur = 0.05  # 50ms micro-fade to act as pop-free cut
            elif t_type == "fade":
                # Only use a real fade (dip to black) if it's the transition to the final shot (last transition)
                if i == n - 2:
                    mapped_type = "fade"
                else:
                    mapped_type = "dissolve"
                mapped_dur = t_dur
            else:
                mapped_type = TRANSITION_MAP.get(t_type, "dissolve")
                mapped_dur = t_dur
                
            # Clamp duration to half the length of the shorter clip
            max_dur = min(durations[i], durations[i+1]) / 2.0
            if mapped_dur > max_dur:
                mapped_dur = max_dur
                
            t_types.append(mapped_type)
            t_durs.append(mapped_dur)

        # Build filter complex
        video_filters = []
        audio_filters = []
        
        # Bookend: Fade-in from black at start of first clip (video/audio)
        video_filters.append("[0:v]fade=t=in:st=0:d=1.0[v_in_faded]")
        audio_filters.append("[0:a]afade=t=in:st=0:d=1.0[a_in_faded]")
        
        cumulative_offset = 0.0

        for i in range(n - 1):
            # Offset formula: O_0 = L_0 - D_0, O_i = O_{i-1} + L_i - D_i
            offset = round(cumulative_offset + durations[i] - t_durs[i], 3)
            offset = max(0.0, offset)

            v_in1 = "[v_in_faded]" if i == 0 else f"[vfade{i-1}]"
            a_in1 = "[a_in_faded]" if i == 0 else f"[afade{i-1}]"

            v_in2 = f"[{i+1}:v]"
            a_in2 = f"[{i+1}:a]"

            v_out = "[vout_temp]" if i == n - 2 else f"[vfade{i}]"
            a_out = "[aout_temp]" if i == n - 2 else f"[afade{i}]"

            video_filters.append(
                f"{v_in1}{v_in2}xfade=transition={t_types[i]}:duration={t_durs[i]}:offset={offset}{v_out}"
            )
            audio_filters.append(
                f"{a_in1}{a_in2}acrossfade=d={t_durs[i]}{a_out}"
            )

            # Keep track of the timeline position of the next clip in the output
            cumulative_offset = offset

        # Bookend: Fade-out to black at end of last clip (video/audio)
        total_duration = round(cumulative_offset + durations[-1], 3)
        fade_out_start = max(0.0, round(total_duration - 1.0, 3))
        
        video_filters.append(f"[vout_temp]fade=t=out:st={fade_out_start}:d=1.0[vout]")
        audio_filters.append(f"[aout_temp]afade=t=out:st={fade_out_start}:d=1.0[aout]")

        filter_complex = ";".join(video_filters + audio_filters)

        cmd = ["ffmpeg", "-y"]
        for p in clip_paths:
            cmd.extend(["-i", p])
        cmd.extend(["-filter_complex", filter_complex])
        cmd.extend(["-map", "[vout]", "-map", "[aout]"])
        cmd.extend([
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-ar", "44100",
            "-ac", "2",
            "-t", str(total_duration),
            str(output_path)
        ])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg xfade failed:\n{result.stderr}")
            
        logger.info("Successfully stitched clips with xfade transitions.")
        return str(output_path)

    except Exception as e:
        logger.error(f"Xfade transition stitching failed: {e}. Falling back to plain concat...")
        return _stitch_concat_demuxer(clip_paths, output_path)


def build_reel_from_segments(
    best_segments: list,
    clips_dir: Path,
    reel_path: Path,
    width: int = 1080,
    height: int = 1920,
    fps: int = 30,
    transitions: list = None,
    transition_durations: list = None,
) -> str:
    """
    High-level helper: trim all segments → re-encode → stitch → return reel path.
    Used by the Celery worker for rendering enqueued video reels.
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
            logger.info(f"  📺 Detected landscape preference ({landscape_count} vs {portrait_count}). Output resolution set to 1920x1080.")
        else:
            width, height = 1080, 1920
            logger.info(f"  📱 Detected portrait preference ({portrait_count} vs {landscape_count}). Output resolution set to 1080x1920.")

    if clips_dir.exists():
        shutil.rmtree(clips_dir)
    clips_dir.mkdir(exist_ok=True)
    ordered_clip_paths = []
    trim_failures      = []

    logger.info(f"\nTrimming {len(used_segments)} clip(s)...")
    for position, seg in enumerate(used_segments):
        role      = seg.get("story_role", seg.get("narrative_role", "clip"))
        src_stem  = Path(seg["video_path"]).stem
        out_path  = clips_dir / f"clip_{position:02d}_{role}_{src_stem}.mp4"
        try:
            rot = seg.get("camera_rotation", 0)
            trim_and_normalize_clip(seg["video_path"], seg["start_sec"], seg["end_sec"], out_path, width, height, fps, rot)
            ordered_clip_paths.append(str(out_path))
            logger.info(f"  [{position}] {role:8s} → {out_path.name}  "
                  f"({seg['start_sec']}s–{seg['end_sec']}s from {Path(seg['video_path']).name})")
        except Exception as e:
            logger.info(f"  [{position}] ✗ Trim failed: {e}")
            fallback = clips_dir / f"clip_{position:02d}_{role}_{src_stem}_FULL_FALLBACK.mp4"
            try:
                shutil.copy(seg["video_path"], str(fallback))
                ordered_clip_paths.append(str(fallback))
                trim_failures.append(position)
                logger.info(f"       → Fallback: full source copied as {fallback.name}")
            except Exception as e2:
                logger.info(f"       → Fallback copy also failed: {e2} — clip {position} dropped.")

    if trim_failures:
        logger.info(f"⚠️  {len(trim_failures)} clip(s) used full-source fallback.")

    if len(ordered_clip_paths) == 0:
        raise RuntimeError("No clips available to stitch.")

    if len(ordered_clip_paths) == 1:
        logger.info("Only 1 clip — skipping stitch, copying directly.")
        shutil.copy(ordered_clip_paths[0], str(reel_path))
    else:
        # Auto-load or compute transitions if not provided
        if transitions is None:
            transitions = []
            transition_durations = []
            
            # 1. Try to load transitions attached directly to the segments from the LLM
            has_attached = False
            if used_segments and any("next_transition" in s for s in used_segments):
                has_attached = True
                for i in range(len(used_segments) - 1):
                    transitions.append(used_segments[i].get("next_transition") or "cut")
                    transition_durations.append(used_segments[i].get("next_transition_duration") or 0.5)
                logger.info(f"Loaded transitions decided by the LLM: {transitions}")
            
            if not has_attached:
                # 2. Try to load from polish_settings.json in the workspace root
                try:
                    workspace_dir = Path(__file__).parent.parent.parent.parent
                    polish_path = workspace_dir / "polish_settings.json"
                    if polish_path.exists():
                        import json
                        with open(polish_path, "r", encoding="utf-8") as f:
                            polish_data = json.load(f)
                            transitions = polish_data.get("transitions", [])
                            transition_durations = [0.5] * len(transitions)
                            logger.info(f"Loaded transitions from polish_settings.json: {transitions}")
                except Exception as e:
                    logger.warning(f"Could not load transitions from polish_settings.json: {e}")

            # 3. If still empty, compute dynamically using footage flow rules
            if not transitions:
                for i in range(len(used_segments) - 1):
                    seg_a = used_segments[i]
                    seg_b = used_segments[i + 1]
                    
                    loc_a = (seg_a.get("location_tag") or "").lower()
                    loc_b = (seg_b.get("location_tag") or "").lower()
                    
                    mood_a = (seg_a.get("mood") or "").lower()
                    mood_b = (seg_b.get("mood") or "").lower()
                    
                    energy_a = float(seg_a.get("energy") or 5)
                    energy_b = float(seg_b.get("energy") or 5)
                    
                    is_last = (i == len(used_segments) - 2)
                    
                    # 1. Sunset / End (Coda) -> circle_crop
                    if is_last and ("sunset" in loc_b or "sunset" in mood_b or "serene" in mood_b or "calm" in mood_b):
                        t = "circle_crop"
                        d = 0.5
                    
                    # 2. High Action (Pool to Pool) -> slide_left / slide_right
                    elif "pool" in loc_a and "pool" in loc_b:
                        t = "slide_left" if (i % 2 == 0) else "slide_right"
                        d = 0.25  # Keep action transitions fast (0.2s - 0.3s)
                        
                    # 3. High Action (Ping Pong to Ping Pong) -> wipe_left / wipe_right
                    elif ("gym" in loc_a or "table" in loc_a or "tennis" in loc_a) and ("gym" in loc_b or "table" in loc_b or "tennis" in loc_b):
                        t = "wipe_left" if (i % 2 == 0) else "wipe_right"
                        d = 0.25  # Keep action transitions fast
                        
                    # 4. Transitioning Space / Bridge -> zoom_dissolve
                    elif loc_a != loc_b and loc_a and loc_b:
                        t = "zoom_dissolve"
                        d = 0.4
                        
                    # 5. Fallback heuristics based on energy / mood
                    elif energy_a >= 7 and energy_b >= 7:
                        t = "slide_left" if (i % 2 == 0) else "slide_right"
                        d = 0.25
                    elif "serene" in mood_b or "peaceful" in mood_b or "calm" in mood_b or "relaxed" in mood_b:
                        t = "dissolve"
                        d = 0.5
                    else:
                        t = "cut"  # Maps to a 0.05s micro-fade
                        d = 0.05
                        
                    transitions.append(t)
                    transition_durations.append(d)
                logger.info(f"Computed dynamic footage transitions: {transitions} with durations {transition_durations}")

        logger.info(f"\nStitching {len(ordered_clip_paths)} clips → {reel_path} ({width}×{height} @ {fps}fps)...")
        stitch_clips(ordered_clip_paths, reel_path, transitions, transition_durations)

    size_mb = reel_path.stat().st_size / 1_000_000
    logger.info(f"✓ Reel saved: {reel_path}  ({size_mb:.1f} MB)")
    return str(reel_path)
