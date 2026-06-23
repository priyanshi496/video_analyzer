import re

with open("../beat_sync/audio_analyzer.py", "r") as f:
    code = f.read()

# Replace BeatMap dataclass and analyze_bgm function
new_code = """
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

def analyze_bgm(bgm_path: str, target_duration: float = 15.0, verbose: bool = False) -> BeatMap:
    path = Path(bgm_path)
    if not path.exists():
        raise FileNotFoundError(f"[BeatSync] BGM file not found: {bgm_path}")

    import librosa
    import numpy as np
    
    logger.info(f"  [BeatSync] Loading BGM with librosa: {path.name} ...")
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
    y_section = y[start_sample:end_sample]
    
    # 3. Beat + Downbeat Grid
    # Using librosa for robust extraction
    tempo, beat_frames = librosa.beat.beat_track(y=y_section, sr=sr)
    tempo_bpm = float(tempo[0] if isinstance(tempo, (list, tuple, np.ndarray)) else tempo)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr)
    
    # Estimate downbeats (every 4th beat)
    downbeat_times = [b for i, b in enumerate(beat_times) if i % 4 == 0]
    
    # 4. Beat Strength
    onset_env = librosa.onset.onset_strength(y=y_section, sr=sr)
    beat_strengths = onset_env[beat_frames]
    
    if len(beat_strengths) > 0 and np.max(beat_strengths) > 0:
        beat_strengths = beat_strengths / np.max(beat_strengths)
    else:
        beat_strengths = np.ones(len(beat_times))
        
    beat_grid = []
    for i, t in enumerate(beat_times):
        rel_time = round(float(t), 3)
        beat_grid.append({
            "time": rel_time,
            "is_downbeat": rel_time in downbeat_times,
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
"""

# Replace from 'import logging' up to 'def extract_audio_energy_map'
code = re.sub(r'import logging.*?def extract_audio_energy_map', new_code + '\n\ndef extract_audio_energy_map', code, flags=re.DOTALL)

with open("../beat_sync/audio_analyzer.py", "w") as f:
    f.write(code)

print("Patch applied.")
