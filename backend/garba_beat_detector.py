"""
garba_beat_detector.py
----------------------
Specialized beat/transient detector for Indian percussion instruments:
dhol, tabla, dholak, nagara — optimized for garba and folk music.

Why a separate detector?
    Generic librosa beat_track() is tuned for Western music (kick drum at ~60-80Hz,
    snare at ~200Hz). Indian percussion sits in different frequency bands:
    - Dhol bass (bayan):  80–200Hz   — the "dhoom" hit
    - Dhol treble (tihoi): 800–2000Hz — the "tak" accent
    - Tabla bayan:        100–300Hz
    - Tabla dayan:        400–1200Hz
    - Nagara:             150–400Hz

    By isolating these frequency bands before detection, we lock cuts
    to the actual drum hit instead of a general energy envelope.

Usage:
    python garba_beat_detector.py --audio garba_track.mp3 --output_dir ./clips/

    # With video stitching:
    python garba_beat_detector.py \
        --audio garba_track.mp3 \
        --clips_dir ./garba_clips/ \
        --output garba_reel.mp4 \
        --style aggressive    # subtle | medium | aggressive

Requirements:
    pip install librosa numpy scipy soundfile ffmpeg-python
    brew install ffmpeg  (or apt install ffmpeg)
"""

import librosa
import numpy as np
import subprocess
import argparse
import json
import os
import tempfile
from pathlib import Path
from scipy import signal
from scipy.ndimage import maximum_filter1d


# ─────────────────────────────────────────────────────
# FREQUENCY BANDS for Indian Percussion
# ─────────────────────────────────────────────────────

INDIAN_PERCUSSION_BANDS = {
    # Primary hits — the "boom" of dhol bayan / tabla bayan
    # These are your main cut points
    "dhol_bass": {
        "low_hz":   80,
        "high_hz":  250,
        "weight":   2.0,     # highest weight — primary beat
        "color":    "🔴",
    },
    # Secondary accent — dhol treble / tihoi stroke
    # The "tak tak" between main beats in garba
    "dhol_treble": {
        "low_hz":   700,
        "high_hz":  2500,
        "weight":   1.2,
        "color":    "🟡",
    },
    # Tabla dayan — mid tones, melodic hits
    "tabla_mid": {
        "low_hz":   300,
        "high_hz":  700,
        "weight":   0.8,
        "color":    "🟢",
    },
    # Nagara / nagada — festival percussion, low mid
    "nagara": {
        "low_hz":   150,
        "high_hz":  400,
        "weight":   1.5,
        "color":    "🟠",
    },
    # Cymbals / manjira (tiny cymbals in garba)
    "manjira": {
        "low_hz":   3000,
        "high_hz":  8000,
        "weight":   0.6,
        "color":    "🔵",
    },
}


# ─────────────────────────────────────────────────────
# CORE: Band-Isolated Transient Detection
# ─────────────────────────────────────────────────────

def bandpass_filter(y: np.ndarray, sr: int, low_hz: float, high_hz: float) -> np.ndarray:
    """
    Isolates a specific frequency band from audio.
    Butterworth filter — clean rolloff, no phase artifacts.
    """
    nyquist = sr / 2.0
    low  = low_hz  / nyquist
    high = high_hz / nyquist

    # Clamp to valid range
    low  = max(0.001, min(low,  0.999))
    high = max(0.001, min(high, 0.999))

    if low >= high:
        return y

    b, a = signal.butter(4, [low, high], btype='band')
    return signal.filtfilt(b, a, y)


def detect_band_transients(
    y: np.ndarray,
    sr: int,
    low_hz: float,
    high_hz: float,
    weight: float = 1.0,
    hop_length: int = 64,
    delta: float = 0.15,
    min_gap_sec: float = 0.1,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Detects transients in a specific frequency band.

    Returns:
        onset_times  — array of timestamps (seconds)
        onset_strength_curve — the full strength envelope (for visualization/debug)
    """
    # Isolate the band
    y_band = bandpass_filter(y, sr, low_hz, high_hz)

    # Onset strength in this band
    onset_env = librosa.onset.onset_strength(
        y=y_band,
        sr=sr,
        hop_length=hop_length,
        aggregate=np.median,
        center=True,
    )

    # Apply weight
    onset_env *= weight

    # Peak picking — find spikes in the envelope using dynamic delta threshold
    max_env = np.max(onset_env) if len(onset_env) > 0 else 0.0
    computed_delta = float(max(0.01, min(delta, float(max_env) * 0.15)))


    min_gap_frames = int(min_gap_sec * sr / hop_length)
    peaks = librosa.util.peak_pick(
        onset_env,
        pre_max=3,
        post_max=3,
        pre_avg=4,
        post_avg=6,
        delta=computed_delta,
        wait=min_gap_frames,
    )

    onset_times = librosa.frames_to_time(peaks, sr=sr, hop_length=hop_length)
    return onset_times, onset_env


def detect_garba_transients(
    audio_path: str,
    style: str = "medium",
    debug: bool = False,
) -> dict:
    """
    Main function — detects dhol/tabla/nagara transients from a garba track.

    style:
        "subtle"     → cuts every ~4 beats (2–3s per clip) — slower, cinematic garba
        "medium"     → cuts every ~2 beats (1–1.5s per clip) — standard garba reel
        "aggressive" → cuts on every primary hit (~0.5s clips) — festival/Navratri energy

    Returns dict with:
        primary_cuts   — main cut points (dhol bass hits) — use these for clip changes
        accent_cuts    — secondary accent hits — use for zoom punch timing
        combined_curve — merged strength envelope
        beat_info      — tempo, time signature estimate
        debug_bands    — per-band results (if debug=True)
    """

    print(f"\n🥁 Loading audio: {audio_path}")
    y, sr = librosa.load(audio_path, sr=44100, mono=True)
    duration = librosa.get_duration(y=y, sr=sr)
    print(f"   Duration: {duration:.1f}s | SR: {sr}Hz")

    hop_length = 64   # ~1.5ms resolution at 44100Hz

    # ── Step 1: Separate harmonic from percussive ──
    print("   Separating percussion from melody...")
    y_harmonic, y_percussive = librosa.effects.hpss(
        y,
        margin=(2.0, 4.0)    # wider margin = cleaner percussion separation
    )

    # ── Step 2: Detect per-band transients ──
    print("   Scanning frequency bands...")
    band_results = {}
    all_strengths = None
    frame_times = None

    for band_name, band_cfg in INDIAN_PERCUSSION_BANDS.items():
        times, strength = detect_band_transients(
            y_percussive,
            sr,
            low_hz=band_cfg["low_hz"],
            high_hz=band_cfg["high_hz"],
            weight=band_cfg["weight"],
            hop_length=hop_length,
            delta=0.15,
            min_gap_sec=0.08,
        )
        band_results[band_name] = {
            "times":    times,
            "strength": strength,
            "count":    len(times),
        }
        print(f"   {band_cfg['color']} {band_name}: {len(times)} hits detected")

        if all_strengths is None:
            all_strengths = strength.copy()
            frame_times = librosa.frames_to_time(
                range(len(strength)), sr=sr, hop_length=hop_length
            )
        else:
            min_len = min(len(all_strengths), len(strength))
            all_strengths[:min_len] += strength[:min_len]

    # ── Step 3: Build primary cut points from dhol bass + nagara ──
    # These are the big "boom" hits — where clips should change
    primary_sources = np.concatenate([
        band_results["dhol_bass"]["times"],
        band_results["nagara"]["times"],
    ])
    primary_sources = np.sort(np.unique(primary_sources))

    # Merge hits within 50ms of each other (same physical hit, double detected)
    primary_cuts = merge_close_hits(primary_sources, min_gap_sec=0.05)

    # Get tempo info early for fallback
    tempo, beat_frames = librosa.beat.beat_track(y=y_percussive, sr=sr)
    tempo = float(tempo.item()) if hasattr(tempo, "item") else (float(tempo[0]) if isinstance(tempo, (list, np.ndarray)) else float(tempo))

    # Fallback if no primary cuts found
    if len(primary_cuts) == 0:
        print("   ⚠️ No band-specific primary hits detected. Falling back to general percussive onsets...")
        fallback_onsets = librosa.onset.onset_detect(
            y=y_percussive,
            sr=sr,
            hop_length=hop_length,
            backtrack=True,
            units='time'
        )
        if len(fallback_onsets) > 0:
            primary_cuts = np.array(fallback_onsets)
        else:
            print("   ⚠️ No general onsets detected. Falling back to tempo beats...")
            primary_cuts = librosa.frames_to_time(beat_frames, sr=sr)


    # ── Step 4: Build accent points from dhol treble + manjira ──
    # These are the "tak tak" — where zoom punch should happen
    accent_sources = np.concatenate([
        band_results["dhol_treble"]["times"],
        band_results["manjira"]["times"],
    ])
    accent_sources = np.sort(np.unique(accent_sources))
    accent_cuts = merge_close_hits(accent_sources, min_gap_sec=0.05)

    # ── Step 5: Apply style — thin out cuts based on energy style ──
    primary_cuts, accent_cuts = apply_style(
        primary_cuts, accent_cuts, style, duration, tempo
    )

    # ── Step 6: Get tempo info ──
    tempo, beat_frames = librosa.beat.beat_track(y=y_percussive, sr=sr)
    tempo = float(tempo.item()) if hasattr(tempo, "item") else (float(tempo[0]) if isinstance(tempo, (list, np.ndarray)) else float(tempo))
    print(f"\n   🎵 Estimated tempo: {tempo:.1f} BPM")
    print(f"   Primary cut points: {len(primary_cuts)}")
    print(f"   Accent points:      {len(accent_cuts)}")
    print(f"   Avg clip duration:  {duration/max(len(primary_cuts),1):.2f}s")

    result = {
        "tempo_bpm":       tempo,
        "duration":        duration,
        "style":           style,
        "primary_cuts":    primary_cuts.tolist(),
        "accent_cuts":     accent_cuts.tolist(),
        "avg_clip_dur":    duration / max(len(primary_cuts), 1),
        "combined_strength": all_strengths.tolist() if all_strengths is not None else [],
        "frame_times":     frame_times.tolist() if frame_times is not None else [],
    }

    if debug:
        result["debug_bands"] = {
            name: {
                "times": data["times"].tolist(),
                "count": data["count"],
            }
            for name, data in band_results.items()
        }

    return result


def merge_close_hits(times: np.ndarray, min_gap_sec: float = 0.05) -> np.ndarray:
    """
    Merges transient hits that are too close together (same physical hit,
    detected twice in adjacent frames).
    Keeps the FIRST hit of each cluster — which is the actual transient start.
    """
    if len(times) == 0:
        return times

    merged = [times[0]]
    for t in times[1:]:
        if t - merged[-1] >= min_gap_sec:
            merged.append(t)

    return np.array(merged)


def apply_style(
    primary: np.ndarray,
    accent: np.ndarray,
    style: str,
    duration: float,
    tempo: float = 120.0,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Thins out cut points based on desired editing style and tempo.
    """
    # Calculate beat duration based on tempo
    beat_dur = 60.0 / max(tempo, 30.0)

    style_config = {
        # One clip per 4 primary hits — slower, fluid
        "subtle": {
            "primary_every_n": 4,
            "min_clip_dur":    3.2 * beat_dur,
        },
        # One clip per 2 primary hits — standard garba reel
        "medium": {
            "primary_every_n": 2,
            "min_clip_dur":    1.6 * beat_dur,
        },
        # Cut on every hit — festival/Navratri max energy
        "aggressive": {
            "primary_every_n": 1,
            "min_clip_dur":    0.8 * beat_dur,
        },
    }

    cfg = style_config.get(style, style_config["medium"])

    # Thin primary cuts
    thinned_primary = primary[::cfg["primary_every_n"]]

    # Enforce minimum clip duration
    filtered = [thinned_primary[0]] if len(thinned_primary) > 0 else []
    for t in thinned_primary[1:]:
        if t - filtered[-1] >= cfg["min_clip_dur"]:
            filtered.append(t)
    thinned_primary = np.array(filtered)

    # Accents: only keep those that fall BETWEEN primary cuts
    # (don't double-hit on same frame as a primary cut)
    filtered_accents = []
    for a in accent:
        too_close_to_primary = any(abs(a - p) < 0.05 for p in thinned_primary)
        if not too_close_to_primary:
            filtered_accents.append(a)

    return thinned_primary, np.array(filtered_accents)


# ─────────────────────────────────────────────────────
# VIDEO STITCHING with zoom punch on garba beats
# ─────────────────────────────────────────────────────

def transcode_to_cfr(input_path: str, output_path: str, fps: int = 30):
    """Convert VFR mobile footage to Constant Frame Rate — MUST run first."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"fps={fps}",
        "-vsync", "cfr",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",
        "-an",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"CFR transcode failed for {input_path}:\n{result.stderr[-300:]}")


def build_garba_reel(
    clip_paths: list[str],
    audio_path: str,
    beat_data: dict,
    output_path: str,
    zoom_style: str = "medium",
    fps: int = 30,
    max_duration: float = 30.0
):
    """
    Stitches clips into a garba reel with:
    - Cuts on dhol bass / nagara primary hits
    - Zoom punch on each cut (intensity based on zoom_style)
    - Accent zoom on secondary dhol treble hits (smaller punch)
    - CFR conversion on all clips before stitching
    """

    zoom_configs = {
        "subtle":     {"primary_zoom": 1.06, "accent_zoom": 1.03, "zoom_frames": 6},
        "medium":     {"primary_zoom": 1.10, "accent_zoom": 1.05, "zoom_frames": 4},
        "aggressive": {"primary_zoom": 1.18, "accent_zoom": 1.08, "zoom_frames": 3},
    }
    zcfg = zoom_configs.get(zoom_style, zoom_configs["medium"])
    primary_zoom  = zcfg["primary_zoom"]
    zoom_frames   = zcfg["zoom_frames"]

    primary_cuts = beat_data["primary_cuts"]
    duration     = min(float(beat_data["duration"]), max_duration)

    # Build windows: (start, end) for each clip, capped by max_duration
    windows = []
    for i, start in enumerate(primary_cuts):
        start_val = float(start)
        if start_val >= duration:
            break
        end_val = float(primary_cuts[i + 1]) if i + 1 < len(primary_cuts) else duration
        end_val = min(end_val, duration)
        windows.append((start_val, end_val))

    if not windows:
        windows.append((0.0, duration))

    def get_actual_duration(p: str) -> float:
        cmd = [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1", p
        ]
        res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if res.returncode == 0:
            try:
                return float(res.stdout.strip())
            except ValueError:
                pass
        return 0.0

    print(f"\n🎬 Building garba reel (capped at {duration:.1f}s)...")
    print(f"   {len(clip_paths)} source clips → {len(windows)} beat windows")
    print(f"   Zoom style: {zoom_style} (intensity: {primary_zoom}x, {zoom_frames} frames)")

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── Step 1: Transcode all clips to CFR ──
        print("\n   Converting clips to CFR (constant frame rate)...")
        cfr_clips = []
        for i, clip in enumerate(clip_paths):
            cfr_path = os.path.join(tmpdir, f"cfr_{i:04d}.mp4")
            transcode_to_cfr(clip, cfr_path, fps=fps)
            cfr_clips.append(cfr_path)
            print(f"   ✅ CFR {i+1}/{len(clip_paths)}: {Path(clip).name}")

        # ── Step 2: Trim each clip to its beat window + apply zoom punch ──
        print("\n   Trimming clips to beat windows + applying zoom punch...")
        processed = []
        actual_durations = []

        for i, (start, end) in enumerate(windows):
            clip       = cfr_clips[i % len(cfr_clips)]
            clip_dur   = end - start
            out_path   = os.path.join(tmpdir, f"proc_{i:04d}.mp4")

            # Zoom punch filter
            zoom_filter = (
                f"zoompan="
                f"z='if(lte(on,{zoom_frames}),"
                f"{primary_zoom}-({primary_zoom}-1)*on/{zoom_frames},"
                f"1)':"
                f"x='iw/2-(iw/zoom/2)':"
                f"y='ih/2-(ih/zoom/2)':"
                f"d=1:"
                f"fps={fps}:"
                f"s=1080x1920"
            )

            cmd = [
                "ffmpeg", "-y",
                "-i", clip,
                "-t", str(clip_dur),
                "-vf", (
                    f"scale=1080:1920:force_original_aspect_ratio=decrease,"
                    f"pad=1080:1920:(ow-iw)/2:(oh-ih)/2,"
                    f"{zoom_filter}"
                ),
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "21",
                "-an",
                "-r", str(fps),
                out_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"   ⚠️  Window {i} failed: {result.stderr[-200:]}")
                continue

            actual_dur = get_actual_duration(out_path)
            if actual_dur <= 0.0:
                print(f"   ⚠️  Trimmed clip {i} is empty or invalid. Skipping.")
                continue

            processed.append({
                "path":       out_path,
                "start":      start,
                "end":        end,
                "duration":   actual_dur,
            })
            actual_durations.append(actual_dur)
            print(f"   ✅ Beat window {i+1}/{len(windows)}: {start:.3f}s → {end:.3f}s (actual={actual_dur:.3f}s)")

        if not processed:
            raise RuntimeError("No clips processed. Check clip paths and FFmpeg installation.")

        # ── Step 3: Concatenate clips using demuxer (snappy cuts on beats) ──
        print("\n   Stitching clips using ffmpeg concat demuxer...")

        if len(processed) == 1:
            concat_path = processed[0]["path"]
        else:
            concat_list_path = os.path.join(tmpdir, "concat_list.txt")
            with open(concat_list_path, "w") as f_list:
                for p in processed:
                    safe_path = p["path"].replace("'", "'\\''")
                    f_list.write(f"file '{safe_path}'\n")

            concat_path = os.path.join(tmpdir, "concat.mp4")
            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", concat_list_path,
                "-c:v", "copy",
                concat_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            print(f"   [DEBUG] Concat ffmpeg return code: {result.returncode}")
            with open("concat_error.log", "w") as f_err:
                f_err.write(result.stderr)
            if result.returncode != 0:
                raise RuntimeError(f"Concat demuxer failed:\n{result.stderr[-500:]}")
            else:
                print(f"   [DEBUG] Concat ffmpeg stderr written to concat_error.log")

            concat_dur = get_actual_duration(concat_path)
            print(f"   [DEBUG] Concat path actual duration: {concat_dur}s")

        # ── Step 4: Mux audio ──
        print("   Adding audio track...")
        audio_dur = get_actual_duration(audio_path)
        print(f"   [DEBUG] Audio path actual duration: {audio_dur}s")
        cmd = [
            "ffmpeg", "-y",
            "-i", concat_path,
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        print(f"   [DEBUG] Mux ffmpeg return code: {result.returncode}")
        if result.returncode != 0:
            raise RuntimeError(f"Audio mux failed:\n{result.stderr[-300:]}")
        else:
            print(f"   [DEBUG] Mux ffmpeg stderr (last 500 chars):\n{result.stderr[-500:]}")

    print(f"\n✅ Garba reel saved: {output_path}")
    return output_path



# ─────────────────────────────────────────────────────
# DEBUG: Save analysis to JSON
# ─────────────────────────────────────────────────────

def save_debug_json(beat_data: dict, output_dir: str):
    """Saves full beat analysis for inspection."""
    path = os.path.join(output_dir, "garba_beat_analysis.json")

    save_data = {k: v for k, v in beat_data.items()
                 if k not in ("combined_strength", "frame_times")}

    with open(path, "w") as f:
        json.dump(save_data, f, indent=2)

    print(f"\n📊 Beat analysis: {path}")


# ─────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Garba beat detector — dhol/tabla/nagara optimized"
    )
    parser.add_argument("--audio",      required=True,
                        help="Path to garba/instrumental MP3 or WAV")
    parser.add_argument("--clips_dir",  default=None,
                        help="Directory of .mp4 clips (optional — skip for analysis only)")
    parser.add_argument("--output",     default="garba_reel.mp4",
                        help="Output reel path")
    parser.add_argument("--style",      default="medium",
                        choices=["subtle", "medium", "aggressive"],
                        help="subtle=slow cuts | medium=balanced | aggressive=Navratri energy")
    parser.add_argument("--max_clips",  type=int, default=None,
                        help="Limit clip count for quick testing")
    parser.add_argument("--debug",      action="store_true",
                        help="Save per-band transient data to JSON")
    parser.add_argument("--analyze_only", action="store_true",
                        help="Run beat analysis only, skip video stitching")
    parser.add_argument("--max_duration", type=float, default=30.0,
                        help="Maximum duration of the output reel in seconds")
    args = parser.parse_args()

    # ── Analyze beats ──
    beat_data = detect_garba_transients(
        args.audio,
        style=args.style,
        debug=args.debug,
    )

    # ── Save debug JSON ──
    output_dir = str(Path(args.output).parent)
    save_debug_json(beat_data, output_dir)

    if args.analyze_only:
        print("\n✅ Analysis complete (--analyze_only mode, skipping video)")
        return

    # ── Build reel ──
    if not args.clips_dir:
        print("\n⚠️  No --clips_dir provided. Use --analyze_only or provide clips.")
        return

    clips_dir  = Path(args.clips_dir)
    clip_paths = sorted([str(p) for p in clips_dir.glob("*.mp4")])

    if not clip_paths:
        print(f"❌ No .mp4 clips in {args.clips_dir}")
        return

    if args.max_clips:
        clip_paths = clip_paths[:args.max_clips]

    print(f"\n📁 Using {len(clip_paths)} clips")

    build_garba_reel(
        clip_paths=clip_paths,
        audio_path=args.audio,
        beat_data=beat_data,
        output_path=args.output,
        zoom_style=args.style,
        max_duration=args.max_duration
    )


    # ── Summary ──
    print("\n" + "="*55)
    print("GARBA BEAT SYNC — SUMMARY")
    print("="*55)
    print(f"  Audio:            {args.audio}")
    print(f"  Tempo:            {beat_data['tempo_bpm']:.1f} BPM")
    print(f"  Style:            {args.style}")
    print(f"  Primary cuts:     {len(beat_data['primary_cuts'])} (dhol bass / nagara)")
    print(f"  Accent points:    {len(beat_data['accent_cuts'])} (dhol treble / manjira)")
    print(f"  Avg clip dur:     {beat_data['avg_clip_dur']:.2f}s")
    print(f"  Output:         {args.output}")
    print("="*55)


if __name__ == "__main__":
    main()
