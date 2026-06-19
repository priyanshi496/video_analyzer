"""
beat_sync/audio_analyzer.py
───────────────────────────────────────────────────────────────────────────────
Uses librosa to analyze a music file and extract:
  - Tempo (BPM)
  - Exact beat timestamps (in seconds, down to millisecond precision)
  - Total song duration

This module has NO dependencies on the backend — it is fully standalone.
───────────────────────────────────────────────────────────────────────────────
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


@dataclass
class BeatMap:
    """
    Holds the complete beat analysis of a background music file.

    Attributes:
        bgm_path        : Absolute path to the analyzed audio file
        tempo_bpm       : Detected tempo in beats-per-minute
        beat_times      : List of beat timestamps in seconds (sorted ascending)
        total_duration_sec : Full duration of the song in seconds
    """
    bgm_path: str
    tempo_bpm: float
    beat_times: List[float] = field(default_factory=list)
    total_duration_sec: float = 0.0

    def __repr__(self) -> str:
        return (
            f"BeatMap(bpm={self.tempo_bpm:.1f}, "
            f"beats={len(self.beat_times)}, "
            f"duration={self.total_duration_sec:.1f}s, "
            f"file='{Path(self.bgm_path).name}')"
        )


def analyze_bgm(bgm_path: str, verbose: bool = False) -> BeatMap:
    """
    Analyze a background music file and return a BeatMap with exact beat timestamps.

    Args:
        bgm_path: Path to the audio file (.mp3, .wav, .aac, .flac, .ogg)
        verbose:  If True, log detailed beat information

    Returns:
        BeatMap dataclass with tempo, beat_times, and total_duration_sec

    Raises:
        FileNotFoundError: If the audio file does not exist
        ImportError: If librosa or soundfile is not installed
        RuntimeError: If the audio file cannot be loaded or analyzed
    """
    path = Path(bgm_path)
    if not path.exists():
        raise FileNotFoundError(
            f"[BeatSync] BGM file not found: {bgm_path}\n"
            f"  → Drop your music file into beat_sync/music/ and update BGM_PATH in beat_sync/config.py"
        )

    # Lazy import so the module can be imported even if librosa is not yet installed
    try:
        import librosa  # type: ignore
        import numpy as np  # type: ignore
    except ImportError as e:
        raise ImportError(
            f"[BeatSync] Missing dependency: {e}\n"
            f"  → Run: pip install -r beat_sync/requirements.txt"
        ) from e

    logger.info(f"  [BeatSync] Analyzing BGM: {path.name} ...")

    try:
        # Load audio — librosa converts to mono float32 by default
        y, sr = librosa.load(str(path), sr=None, mono=True)
    except Exception as e:
        raise RuntimeError(f"[BeatSync] Failed to load audio file '{bgm_path}': {e}") from e

    # Total duration in seconds
    total_duration_sec = float(librosa.get_duration(y=y, sr=sr))

    # Beat tracking — returns (tempo_bpm, beat_frame_indices)
    # units='time' returns beat timestamps in seconds directly
    try:
        tempo_arr, beat_frames = librosa.beat.beat_track(y=y, sr=sr, units="frames")
        # Handle both scalar and array tempo (librosa >= 0.10 returns array)
        tempo_bpm = float(np.atleast_1d(tempo_arr)[0])
        beat_times_arr = librosa.frames_to_time(beat_frames, sr=sr)
        beat_times = [round(float(t), 4) for t in beat_times_arr]
    except Exception as e:
        raise RuntimeError(f"[BeatSync] Beat tracking failed: {e}") from e

    beat_map = BeatMap(
        bgm_path=str(path),
        tempo_bpm=tempo_bpm,
        beat_times=beat_times,
        total_duration_sec=total_duration_sec,
    )

    logger.info(
        f"  [BeatSync] ✓ Beat analysis complete: "
        f"{tempo_bpm:.1f} BPM, {len(beat_times)} beats, {total_duration_sec:.1f}s total"
    )

    if verbose:
        logger.info(f"  [BeatSync] Beat times (first 20): {beat_times[:20]}")

    return beat_map


def extract_audio_energy_map(audio_path: str, num_bins: int = 10) -> list:
    """
    Split the audio file into N equal duration chunks, compute the average RMS energy 
    for each chunk, and normalize the energy scores to a 1.0 - 10.0 scale.
    """
    import librosa
    import numpy as np
    
    try:
        y, sr = librosa.load(audio_path, sr=None, mono=True)
    except Exception as e:
        logger.warning(f"  [BeatSync] Failed to load audio for energy map extraction: {e}")
        return []
        
    duration = float(librosa.get_duration(y=y, sr=sr))
    
    # Compute RMS energy
    rms = librosa.feature.rms(y=y)[0]
    times = librosa.times_like(rms, sr=sr)
    
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
        response = call_openrouter_text(prompt, model="nvidia/nemotron-3-nano-omni-30b-a3b-reasoning", fallbacks=["google/gemini-flash-1.5-8b"])
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
        
        # Determine energy score for the current beat
        energy_score = 5.0
        if energy_map:
            for e_bin in energy_map:
                if e_bin.get("start_sec", 0) <= current_start <= e_bin.get("end_sec", float('inf')):
                    energy_score = e_bin.get("energy_score", 5.0)
                    break
        
        # High energy -> very fast cuts (single beat). Target dur ~0.1s so it closes immediately
        # Medium/Low energy -> slower cuts (skip beats). Target dur ~1.5s or 2.0s
        if energy_score >= 7.5:
            target_dur = 0.1
        else:
            target_dur = 1.5 if current_index % 2 == 0 else 2.0
        
        if dur >= target_dur or dur >= max_dur_sec:
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
