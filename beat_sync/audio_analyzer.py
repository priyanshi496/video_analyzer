"""
beat_sync/audio_analyzer.py
───────────────────────────────────────────────────────────────────────────────
Uses madmom to analyze a music file and extract:
  - Tempo (BPM)
  - Exact beat and downbeat timestamps (in seconds, down to millisecond precision)
  - Total song duration

This module has NO dependencies on the backend — it is fully standalone.
───────────────────────────────────────────────────────────────────────────────
"""


import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

@dataclass
class BeatMap:
    bgm_path: str
    tempo_bpm: float
    beat_grid: List[Dict] = field(default_factory=list)  # {time, is_downbeat, strength}
    best_section_start: float = 0.0
    best_section_end: float = 0.0
    total_duration_sec: float = 0.0

    def __repr__(self) -> str:
        return (
            f"BeatMap(bpm={self.tempo_bpm:.1f}, "
            f"beats={len(self.beat_grid)}, "
            f"section=[{self.best_section_start:.1f}s-{self.best_section_end:.1f}s], "
            f"file='{Path(self.bgm_path).name}')"
        )

def run_demucs(audio_path: str) -> str:
    """
    Run Demucs to separate vocals from instruments.
    Returns the path to the 'no_vocals' instrument stem.
    """
    import subprocess
    import sys
    from pathlib import Path

    logger.info(f"  [BeatSync] Running Demucs on {audio_path}...")
    output_dir = Path(audio_path).parent / "demucs_output"
    
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "--two-stems=vocals",
        "-n", "htdemucs",
        "-o", str(output_dir),
        audio_path
    ]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        logger.error(f"  [BeatSync] Demucs failed: {e.stderr.decode('utf-8') if e.stderr else str(e)}")
        raise

    base_name = Path(audio_path).stem
    no_vocals_path = output_dir / "htdemucs" / base_name / "no_vocals.wav"
    
    if not no_vocals_path.exists():
        raise FileNotFoundError(f"Expected Demucs output not found at {no_vocals_path}")
        
    return str(no_vocals_path)

def analyze_bgm(bgm_path: str, target_duration: float = 15.0, verbose: bool = False) -> BeatMap:
    path = Path(bgm_path)
    if not path.exists():
        raise FileNotFoundError(f"[BeatSync] BGM file not found: {bgm_path}")

    # --- Run Demucs to isolate instruments ---
    base_name = path.stem
    output_dir = path.parent / "demucs_output"
    no_vocals_path = output_dir / "htdemucs" / base_name / "no_vocals.wav"
    
    if not no_vocals_path.exists():
        try:
            instrument_path = run_demucs(str(path))
        except Exception as e:
            logger.warning(f"  [BeatSync] Demucs failed, falling back to original audio: {e}")
            instrument_path = str(path)
    else:
        logger.info(f"  [BeatSync] Found cached Demucs instrument stem: {no_vocals_path}")
        instrument_path = str(no_vocals_path)

    import librosa
    import numpy as np
    
    logger.info(f"  [BeatSync] Loading full BGM for structure: {path.name} ...")
    y, sr = librosa.load(str(path), sr=22050)
    total_duration_sec = librosa.get_duration(y=y, sr=sr)
    
    # 1. Structural Analysis: Find best section
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    
    # Simple heuristic: find a window of target_duration with highest mean RMS
    window_frames = int(target_duration * sr / 512) # hop_length is 512
    if len(rms) > window_frames:
        window_sums = np.convolve(rms, np.ones(window_frames), 'valid')
        best_start_frame = np.argmax(window_sums)
        best_section_start = librosa.frames_to_time(best_start_frame, sr=sr)
    else:
        best_section_start = 0.0
        
    best_section_end = min(best_section_start + target_duration, total_duration_sec)
    
    # 2. Extract section
    start_sample = int(best_section_start * sr)
    end_sample = int(best_section_end * sr)
    
    # Load the isolated instrument stem specifically for beat detection
    logger.info(f"  [BeatSync] Loading instrument stem for beats: {Path(instrument_path).name} ...")
    y_inst, _ = librosa.load(instrument_path, sr=sr)
    
    # Ensure y_inst is long enough (in case demucs output is slightly truncated)
    if len(y_inst) < end_sample:
        y_inst = np.pad(y_inst, (0, end_sample - len(y_inst)))
        
    y_section = y_inst[start_sample:end_sample]
    y_section_full = y[start_sample:end_sample]
    
    # 3. Beat Extraction (Major Spikes only)
    # Use peak picking on onset strength to find major drops instead of strict tempo grid
    from scipy.signal import find_peaks
    onset_env = librosa.onset.onset_strength(y=y_section, sr=sr)
    
    # Keep librosa's beat track just to get the overall BPM for metadata (using full audio)
    tempo, _ = librosa.beat.beat_track(y=y_section_full, sr=sr)
    tempo_bpm = float(tempo[0] if isinstance(tempo, (list, tuple, np.ndarray)) else tempo)
    
    if np.max(onset_env) > 0:
        onset_env = onset_env / np.max(onset_env)
        
    min_dist_frames = int(0.8 * sr / 512)
    peaks, _ = find_peaks(onset_env, prominence=0.35, distance=min_dist_frames)
    if len(peaks) < 5:
        peaks, _ = find_peaks(onset_env, prominence=0.2, distance=min_dist_frames)
        
    beat_times = librosa.frames_to_time(peaks, sr=sr)
    beat_times = [t + best_section_start for t in beat_times]
    
    # We no longer rely on rigid downbeats since we have pure energy spikes
    downbeat_times = []
    
    # 4. Beat Strength
    beat_strengths = onset_env[peaks] if len(peaks) > 0 else np.ones(len(beat_times))
    
    beat_grid = []
    for i, t in enumerate(beat_times):
        rel_time = round(float(t), 3)
        beat_grid.append({
            "time": rel_time,
            "is_downbeat": False,
            "strength": round(float(beat_strengths[i]), 3)
        })
        
    beat_map = BeatMap(
        bgm_path=str(path),
        tempo_bpm=tempo_bpm,
        beat_grid=beat_grid,
        best_section_start=best_section_start,
        best_section_end=best_section_end,
        total_duration_sec=total_duration_sec
    )
    
    logger.info(f"  [BeatSync] ✓ Beat analysis complete: {tempo_bpm:.1f} BPM, section {best_section_start:.1f}-{best_section_end:.1f}")
    return beat_map


def extract_audio_energy_map(audio_path: str, num_bins: int = 10) -> list:
    """
    Split the audio file into N equal duration chunks, compute the average RMS energy 
    for each chunk, and normalize the energy scores to a 1.0 - 10.0 scale.
    """
    import soundfile as sf
    import numpy as np
    
    try:
        y, sr = sf.read(audio_path)
        # Convert to mono if it's stereo
        if len(y.shape) > 1:
            y = np.mean(y, axis=1)
    except Exception as e:
        logger.warning(f"  [BeatSync] Failed to load audio for energy map extraction: {e}")
        return []
        
    duration = float(len(y)) / sr
    
    # Compute RMS energy per frame (e.g. 512 samples) to save memory/time
    frame_length = 512
    # Pad y if necessary
    if len(y) % frame_length != 0:
        pad_width = frame_length - (len(y) % frame_length)
        y = np.pad(y, (0, pad_width), mode='constant')
        
    y_framed = y.reshape(-1, frame_length)
    rms = np.sqrt(np.mean(y_framed**2, axis=1))
    
    # Create time array for each frame's center
    times = np.arange(len(rms)) * (frame_length / sr) + (frame_length / (2 * sr))
    
    bin_duration = duration / num_bins
    energy_bins = []
    
    for i in range(num_bins):
        start_t = i * bin_duration
        end_t = (i + 1) * bin_duration
        # Get RMS values in this time window
        mask = (times >= start_t) & (times <= end_t)
        if np.any(mask):
            avg_energy = float(np.mean(rms[mask]))
        else:
            avg_energy = 0.0
        energy_bins.append((round(start_t, 2), round(end_t, 2), avg_energy))
        
    # Normalize energy to 1-10 scale
    max_energy = max(b[2] for b in energy_bins) if energy_bins else 1.0
    if max_energy == 0.0:
        max_energy = 1.0
        
    normalized_bins = []
    for start, end, eng in energy_bins:
        scale = round((eng / max_energy) * 9.0 + 1.0, 1) # 1.0 to 10.0
        if scale >= 7.5:
            cat = "Peak Energy (Drop/Chorus/Hook)"
        elif scale >= 4.5:
            cat = "Medium Energy (Build-up/Verse)"
        else:
            cat = "Low Energy (Intro/Outro/Break)"
        normalized_bins.append({
            "start_sec": start,
            "end_sec": end,
            "energy_score": scale,
            "description": cat
        })
        
    return normalized_bins


def analyze_audio_hooks_with_llm(song_name: str, bpm: float, duration: float, energy_map: list) -> dict:
    """
    Use Nemotron to identify key hooks, drops, and build-ups in the song based on the energy map.
    """
    import json
    try:
        from app.services.llm_service import call_openrouter_text
    except ImportError:
        logger.warning("  [BeatSync] app.services.llm_service could not be imported — skipping LLM audio hook analysis.")
        return _fallback_audio_analysis(energy_map)
    
    prompt = f"""You are a professional audio supervisor and video editor.
Analyze the following background music track properties and energy profile:
- Song File: {song_name}
- Tempo: {bpm:.1f} BPM
- Total Duration: {duration:.2f} seconds

Energy Profile over time chunks:
{json.dumps(energy_map, indent=2)}

Based on the energy score (1-10) and duration, identify 2-4 critical structural 'hooks' (e.g. build-ups, drops, choruses, high energy segments) of the song.
Return your analysis strictly in JSON format with the following schema:
{{
  "music_summary": "Overall style, rhythm, and dynamic flow of the song.",
  "vibe_recommendation": "What kind of video vibe or content theme matches this song best.",
  "hooks": [
    {{
      "start_sec": float,
      "end_sec": float,
      "hook_type": "drop" | "chorus" | "build-up" | "intro",
      "energy_level": "high" | "medium" | "low",
      "editing_instruction": "How the video clips should behave here (e.g., fast cuts, slow motion, dramatic transition)."
    }}
  ]
}}
Do not include any thinking, explanations, markdown formatting (no ```json code blocks), or extra text outside the JSON. Return only the JSON object.
"""
    try:
        # Call the Nemotron-3 reasoning model
        response = call_openrouter_text(prompt, model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", fallbacks=["google/gemini-1.5-flash-8b"])
        from app.services.prompts_service import parse_json_response
        parsed = parse_json_response(response)
        if isinstance(parsed, dict) and "hooks" in parsed:
            return parsed
        raise ValueError("Invalid hook analysis format received from LLM")
    except Exception as e:
        logger.warning(f"  [BeatSync] Failed to obtain custom LLM hook analysis: {e}. Using rule-based fallback.")
        return _fallback_audio_analysis(energy_map)


def build_beat_windows(
    beat_times: list[float],
    bgm_start_sec: float,
    total_target_duration: float = 15.0,
    min_dur_sec: float = 1.0,
    max_dur_sec: float = 2.5,
    energy_map: list[dict] = None,
) -> list[dict]:
    """
    Chunks a continuous list of beat timestamps into distinct "beat windows" 
    starting from `bgm_start_sec`. Each window will be between min_dur_sec and max_dur_sec.
    These windows are used to explicitly instruct the Story Order LLM where cuts must happen.

    Returns a list of dicts:
    [
      { "window_index": 0, "start_sec": 30.33, "end_sec": 31.55, "duration": 1.22, "num_beats": 3 },
      ...
    ]
    """
    # Filter beats to only those after the chosen hook
    valid_beats = [b for b in beat_times if b >= bgm_start_sec]
    if not valid_beats:
        return []

    windows = []
    current_start = valid_beats[0]
    current_index = 0
    beat_idx = 1
    
    while beat_idx < len(valid_beats):
        current_beat = valid_beats[beat_idx]
        dur = current_beat - current_start
        
        # We cut strictly on every major beat found, no arbitrary target_dur
        windows.append({
            "window_index": current_index,
            "start_sec": round(current_start, 3),
            "end_sec": round(current_beat, 3),
            "duration": round(dur, 3),
        })
        current_start = current_beat
        current_index += 1
            
            # Stop if we have enough windows to fill the reel
            total_time_covered = current_start - valid_beats[0]
            if total_time_covered >= total_target_duration:
                break
                
        beat_idx += 1
        
    return windows


def _fallback_audio_analysis(energy_map: list) -> dict:
    # Rule-based fallback if LLM call fails
    hooks = []
    for entry in energy_map:
        if entry["energy_score"] >= 6.0:
            hooks.append({
                "start_sec": entry["start_sec"],
                "end_sec": entry["end_sec"],
                "hook_type": "chorus" if entry["energy_score"] >= 8.0 else "build-up",
                "energy_level": "high" if entry["energy_score"] >= 8.0 else "medium",
                "editing_instruction": "Match with high-motion or climax visual segments."
            })
    return {
        "music_summary": "Rhythmic background music with variable energy stages.",
        "vibe_recommendation": "Dynamic, tempo-matched visual cuts and pacing.",
        "hooks": hooks
    }


# ── Standalone test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # Use config path by default, or pass a path as CLI arg
    if len(sys.argv) > 1:
        test_path = sys.argv[1]
    else:
        from config import BGM_PATH
        test_path = BGM_PATH

    try:
        bm = analyze_bgm(test_path, verbose=True)
        print(f"\n{bm}")
        print(f"First 10 beats: {bm.beat_times[:10]}")
        print(f"Last  10 beats: {bm.beat_times[-10:]}")
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
