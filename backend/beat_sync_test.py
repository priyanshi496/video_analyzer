"""
beat_sync_test.py
-----------------
Standalone beat-sync tester for instrumental tracks.
Does NOT touch your main pipeline — safe to run locally.

Usage:
    python beat_sync_test.py --audio track.mp3 --clips_dir ./clips/ --output output.mp4

Requirements:
    pip install librosa numpy scipy ffmpeg-python
    Optional (for neural onset detection): pip install madmom
    ffmpeg must be installed on your system (brew install ffmpeg / apt install ffmpeg)
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

# ── Optional: madmom neural onset detection ──────────────────────────
try:
    from madmom.features.onsets import CNNOnsetProcessor
    from madmom.features.beats import DBNBeatTrackingProcessor
    MADMOM_AVAILABLE = True
    print("[madmom] Neural onset detection ENABLED")
except ImportError:
    MADMOM_AVAILABLE = False


# ─────────────────────────────────────────────
# STEP 0: Preprocessing (VFR to CFR)
# ─────────────────────────────────────────────

def transcode_to_cfr(input_path: str, output_path: str, fps: int = 30):
    """
    Convert VFR (Variable Frame Rate) mobile footage to Constant Frame Rate (CFR).
    This ensures that 1 second of video matches 1 second of audio exactly.
    """
    print(f"   🔄 Transcoding to CFR ({fps} fps): {Path(input_path).name}")
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vf", f"fps={fps}",          # force constant frame rate
        "-vsync", "cfr",              # constant frame rate mode
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "18",                 # visually lossless quality
        "-c:a", "copy",
        output_path
    ]
    subprocess.run(cmd, check=True, capture_output=True)


# ─────────────────────────────────────────────
# STEP 1: Accurate Onset and Transient Analysis
# ─────────────────────────────────────────────

EDIT_LAYERS = {
    "kick":      {"low_hz": 40,   "high_hz": 100,  "weight": 10, "source": "percussive", "transition": "fade", "transition_duration": 0.034},
    "snare":     {"low_hz": 150,  "high_hz": 350,  "weight": 8,  "source": "percussive", "transition": "fade", "transition_duration": 0.034},
    "bass_hit":  {"low_hz": 80,   "high_hz": 200,  "weight": 7,  "source": "percussive", "transition": "fade", "transition_duration": 0.034},
    "vocal":     {"low_hz": 200,  "high_hz": 3000, "weight": 6,  "source": "harmonic",   "transition": "fade", "transition_duration": 0.034},
    "hi_hat":    {"low_hz": 4000, "high_hz": 10000,"weight": 3,  "source": "percussive", "transition": "fade", "transition_duration": 0.034},
}

# Waveform chart: color-code each event type
EVENT_COLORS = {
    "drop":           "#FF3B30",   # RED       — big impact
    "energy_rise":    "#FF9500",   # ORANGE    — energy rise
    "energy_fall":    "#FF2D55",   # MAGENTA   — energy release
    "spectral_flux":  "#BF5AF2",   # PURPLE    — spectral change
    "structural":     "#FF6BD6",   # PINK      — section boundary (novelty)
    "onset":          "#FFFFFF",   # WHITE     — librosa onset strength
    "silence_end":    "#5AC8FA",   # CYAN      — post-silence attack
    "kick":           "#FFD60A",   # YELLOW    — kick drum
    "snare":          "#30D158",   # GREEN     — snare hit
    "bass_hit":       "#FF6B35",   # AMBER     — bass hit
    "vocal":          "#0A84FF",   # BLUE      — vocal attack
    "hi_hat":         "#8E8E93",   # GRAY      — hi-hat
    "tempo":          "#636366",   # DARK GRAY — tempo-grid fallback
    "force":          "#3A3A3C",   # DARKER    — forced cut
    "start":          "#00C7BE",   # TEAL      — start
}

# ── Event Tier System ─────────────────────────────────────────────────
# Tier 1 = ALWAYS change the clip  (high musical importance)
# Tier 2 = change clip if score >= threshold, else apply zoom/flash
# Tier 3 = visual effect only (no clip change)
EVENT_TIERS = {
    "drop":           1,
    "structural":     1,
    "silence_end":    1,
    "energy_rise":    1,
    "onset":          2,
    "kick":           2,
    "snare":          2,
    "bass_hit":       2,
    "vocal":          2,
    "energy_fall":    2,
    "spectral_flux":  2,
    "hi_hat":         3,
    "tempo":          2,
    "force":          3,
    "start":          1,
}
TIER2_CUT_SCORE_THRESHOLD = 45.0   # Tier-2 events with score >= this become clip cuts

EVENT_MULTIPLIERS = {
    "drop":          4.0,
    "structural":    3.5,
    "silence_end":   3.5,
    "energy_rise":   3.0,
    "vocal":         2.5,
    "bass_hit":      2.5,
    "spectral_flux": 2.0,
    "snare":         1.8,
    "kick":          1.5,
    "onset":         1.0,
    "hi_hat":        0.5
}


def get_event_tier(event: dict) -> int:
    """
    Returns the action tier for an event:
      1 = always cut to new clip
      2 = cut if score is high enough, else zoom/flash
      3 = visual-only effect
    """
    base_tier = EVENT_TIERS.get(event.get("type", "force"), 3)
    if base_tier == 2:
        score = event.get("score", event.get("weight", 0.0))
        if score >= TIER2_CUT_SCORE_THRESHOLD:
            return 1   # promoted
    return base_tier

def bandpass_filter(y: np.ndarray, sr: int, low_hz: float, high_hz: float) -> np.ndarray:
    """
    Isolates a specific frequency band from audio.
    """
    nyquist = sr / 2.0
    low  = low_hz  / nyquist
    high = high_hz / nyquist

    low  = max(0.001, min(low,  0.999))
    high = max(0.001, min(high, 0.999))

    if low >= high:
        return y

    sos = signal.butter(4, [low, high], btype='band', output='sos')
    return signal.sosfiltfilt(sos, y)


def compute_band_onset_envelope(y_band: np.ndarray, hop_length: int = 64) -> np.ndarray:
    """
    Computes a stable onset strength envelope directly from the band-isolated signal's amplitude envelope.
    Returns (envelope, peak_values) — peak_values allows score-based ranking.
    """
    frame_length = hop_length * 4
    squared = y_band ** 2
    window = np.ones(frame_length) / frame_length
    energy = np.convolve(squared, window, mode='same')
    amplitude_env = np.sqrt(np.maximum(1e-10, energy))
    amplitude_env_down = amplitude_env[::hop_length]
    diff = np.diff(amplitude_env_down, prepend=amplitude_env_down[0])
    return np.maximum(0.0, diff).astype(np.float32)


def compute_event_score(base_weight: float, transient_strength: float,
                        energy_jump: float = 0.0, structural_novelty: float = 0.0) -> float:
    """
    Composite score that differentiates 'weak kick' vs 'huge drop kick'.
    Score replaces flat weight for best-event selection.
    """
    return (
        base_weight       * 2.0
        + transient_strength * 4.0
        + energy_jump        * 5.0
        + structural_novelty * 8.0
    )


def detect_band_transients(
    y: np.ndarray,
    sr: int,
    low_hz: float,
    high_hz: float,
    hop_length: int = 64,
    delta: float = 0.12,
    min_gap_sec: float = 0.05
) -> tuple[np.ndarray, np.ndarray]:
    """Returns (times, normalized_strengths) for score-based ranking."""
    y_band = bandpass_filter(y, sr, low_hz, high_hz)
    
    # Stable energy-envelope onset detection
    onset_env = compute_band_onset_envelope(y_band, hop_length=hop_length)
    
    max_env = np.max(onset_env) if len(onset_env) > 0 else 0.0
    computed_delta = float(max_env * delta)
    
    min_gap_frames = int(min_gap_sec * sr / hop_length)
    peaks = librosa.util.peak_pick(
        onset_env,
        pre_max=2,
        post_max=2,
        pre_avg=2,
        post_avg=4,
        delta=computed_delta,
        wait=min_gap_frames
    )
    times = librosa.frames_to_time(peaks, sr=sr, hop_length=hop_length)
    # Normalized strength of each peak (0..1)
    strengths = onset_env[peaks] / (max_env + 1e-8) if len(peaks) > 0 else np.array([])
    return times, strengths


def merge_and_resolve_events(events: list[dict], min_gap_sec: float = 0.05) -> list[dict]:
    """
    Merges events within min_gap_sec, keeping the one with the highest composite SCORE
    (not flat weight). Score distinguishes weak vs strong instances of the same event type.
    """
    if not events:
        return []
    
    sorted_events = sorted(events, key=lambda x: x["time"])
    
    merged = []
    current_group = [sorted_events[0]]
    
    for ev in sorted_events[1:]:
        if ev["time"] - current_group[-1]["time"] <= min_gap_sec:
            current_group.append(ev)
        else:
            # Use composite score; fall back to weight if score absent
            best_event = max(current_group, key=lambda x: x.get("score", x["weight"]))
            best_event_copy = best_event.copy()
            best_event_copy["time"] = current_group[0]["time"]
            merged.append(best_event_copy)
            current_group = [ev]
            
    if current_group:
        best_event = max(current_group, key=lambda x: x.get("score", x["weight"]))
        best_event_copy = best_event.copy()
        best_event_copy["time"] = current_group[0]["time"]
        merged.append(best_event_copy)
        
    return merged


def detect_silences(y: np.ndarray, sr: int, top_db: float = 35) -> list[dict]:
    non_silent = librosa.effects.split(y, top_db=top_db)
    duration = librosa.get_duration(y=y, sr=sr)
    
    silences = []
    last_end = 0.0
    
    for start_frame, end_frame in non_silent:
        start_time = float(librosa.samples_to_time(start_frame, sr=sr))
        end_time = float(librosa.samples_to_time(end_frame, sr=sr))
        
        if start_time - last_end >= 0.2:  # Silence must be at least 200ms
            silences.append({
                "time": max(0.0, start_time - 0.05),
                "type": "silence_end",
                "weight": 9.0,
                "transition": "zoomin",
                "transition_duration": 0.15
            })
        last_end = end_time
         
    return silences


def detect_drops(y: np.ndarray, sr: int, hop_length: int = 512) -> list[dict]:
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
    times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)
    
    frames_0_1s = max(1, int(0.1 * sr / hop_length))
    
    drops = []
    for i in range(frames_0_1s, len(rms)):
        prev_min = np.min(rms[i - frames_0_1s : i])
        if prev_min > 0.005 and rms[i] / prev_min >= 3.0:
            ratio = float(rms[i] / (prev_min + 1e-8))
            score = compute_event_score(11.0, min(ratio / 10.0, 1.0), energy_jump=1.0)
            drops.append({
                "time": float(times[i]),
                "type": "drop",
                "weight": 11.0,
                "score": score,
                "transition": "zoomin",
                "transition_duration": 0.15
            })
            
    thinned_drops = []
    if drops:
        thinned_drops.append(drops[0])
        for d in drops[1:]:
            if d["time"] - thinned_drops[-1]["time"] >= 1.0:
                thinned_drops.append(d)
                
    return thinned_drops


def detect_rms_energy_events(y: np.ndarray, sr: int, hop_length: int = 512,
                              min_gap_sec: float = 0.5) -> list[dict]:
    """
    Detects energy rises and falls using Savitzky-Golay smoothed RMS gradient.
    Percentile-based thresholds adapt to any audio level — no magic number needed.

    Why Savitzky-Golay:
      - Preserves peak shape better than simple moving average
      - Critical for correctly locating the moment of a drop vs. the decay after it
    """
    from scipy.signal import savgol_filter

    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length)[0]
    times = librosa.frames_to_time(range(len(rms)), sr=sr, hop_length=hop_length)

    # Savitzky-Golay: window must be odd and > polyorder
    win = min(21, (len(rms) // 2) * 2 - 1)
    win = max(win, 5)
    smooth = savgol_filter(rms, window_length=win, polyorder=3)

    gradient = np.gradient(smooth)
    rise_threshold = np.percentile(gradient, 95)   # top 5% of rises
    drop_threshold = np.percentile(gradient, 5)    # bottom 5% of falls
    max_grad = np.max(np.abs(gradient)) + 1e-8

    events = []
    last_rise = -min_gap_sec
    last_fall = -min_gap_sec

    for t, g in zip(times, gradient):
        if g > rise_threshold and t - last_rise > min_gap_sec:
            strength = float(g / max_grad)
            score = compute_event_score(8.5, strength, energy_jump=strength * 1.2)
            events.append({
                "time": float(t),
                "type": "energy_rise",
                "weight": 8.5,
                "score": score,
                "transition": "fade",
                "transition_duration": 0.034
            })
            last_rise = t
        elif g < drop_threshold and t - last_fall > min_gap_sec:
            strength = float(abs(g) / max_grad)
            score = compute_event_score(7.5, strength, energy_jump=strength)
            events.append({
                "time": float(t),
                "type": "energy_fall",
                "weight": 7.5,
                "score": score,
                "transition": "fade",
                "transition_duration": 0.034
            })
            last_fall = t

    return events


def detect_onset_strength_events(y: np.ndarray, sr: int, hop_length: int = 512,
                                  min_gap_sec: float = 0.08) -> list[dict]:
    """
    Uses librosa's onset_strength with median aggregation.
    Catches micro-spikes missed by bandpass:
      - vocal consonants, claps, hi-hat openings, camera shutter sounds, impacts.
    backtrack=True snaps each onset to the actual start of the transient (not the peak).
    """
    onset_env = librosa.onset.onset_strength(
        y=y, sr=sr,
        hop_length=hop_length,
        aggregate=np.median,
        fmax=8000   # perceptually important range
    )
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env,
        sr=sr,
        hop_length=hop_length,
        backtrack=True,
        units='frames'
    )
    if len(onset_frames) == 0:
        return []

    times = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length)
    max_env = np.max(onset_env) + 1e-8
    strengths = onset_env[onset_frames] / max_env

    events = []
    last_t = -min_gap_sec
    for t, s in zip(times, strengths):
        if t - last_t < min_gap_sec:
            continue
        score = compute_event_score(9.0, float(s), energy_jump=float(s) * 0.3)
        events.append({
            "time": float(t),
            "type": "onset",
            "weight": 9.0 * float(s),
            "score": score,
            "transition": "fade",
            "transition_duration": 0.034
        })
        last_t = t
    return events


def detect_novelty_events(y: np.ndarray, y_harmonic: np.ndarray, sr: int,
                           hop_length: int = 512, n_events: int | None = None) -> list[dict]:
    """
    Detects structural section boundaries (verse→pre-chorus→chorus→drop)
    using checkerboard novelty on the mel + chroma self-similarity matrix.

    These are the moments editors ALWAYS cut on but transient detectors miss.
    A novelty peak = 'the music just changed character'.
    """
    try:
        duration = librosa.get_duration(y=y, sr=sr)
        if n_events is None:
            n_events = max(4, int(duration / 10))
        # Mel spectrogram (timbre)
        S = librosa.feature.melspectrogram(y=y, sr=sr, hop_length=hop_length, n_mels=64)
        log_S = librosa.power_to_db(S)

        # Chroma (harmony)
        C = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr, hop_length=hop_length)

        # Stack top mel bands + chroma, normalize per-feature
        features = np.vstack([log_S[:12], C])         # 12 mel + 12 chroma = 24 features
        features = librosa.util.normalize(features, axis=1)

        # Self-similarity matrix
        R = librosa.segment.recurrence_matrix(features, mode='affinity', sym=True)

        # Lag representation → diagonal = novelty curve
        lag = librosa.segment.recurrence_to_lag(R)
        novelty = np.abs(np.diff(lag.diagonal(), prepend=lag.diagonal()[0]))
        novelty_smooth = np.convolve(novelty, np.ones(7) / 7, mode='same')

        times = librosa.frames_to_time(range(len(novelty_smooth)), sr=sr, hop_length=hop_length)
        max_nov = np.max(novelty_smooth) + 1e-8

        # Pick top N distinct peaks (at least 1 second apart)
        peak_indices = librosa.util.peak_pick(
            novelty_smooth,
            pre_max=10, post_max=10, pre_avg=20, post_avg=20,
            delta=float(np.percentile(novelty_smooth, 75)),
            wait=int(1.0 * sr / hop_length)
        )

        events = []
        for idx in peak_indices[:n_events]:
            t = float(times[idx])
            strength = float(novelty_smooth[idx] / max_nov)
            score = compute_event_score(9.5, strength, structural_novelty=strength * 1.5)
            events.append({
                "time": t,
                "type": "structural",
                "weight": 9.5,
                "score": score,
                "transition": "fade",
                "transition_duration": 0.034
            })
        return events
    except Exception as e:
        print(f"   ⚠️  Novelty curve failed: {e}")
        return []


def detect_spectral_flux_events(y: np.ndarray, sr: int, hop_length: int = 512,
                                 threshold_percentile: float = 90,
                                 min_gap_sec: float = 0.5) -> list[dict]:
    """
    Detects structural musical changes using spectral flux.
    Large flux values = 'something changed dramatically in the music'.
    These are prime edit points (section boundaries, drops, builds).
    """
    S = np.abs(librosa.stft(y, hop_length=hop_length))
    # Positive spectral flux only (onsets, not offsets)
    flux = np.sum(np.diff(S, axis=1, prepend=S[:, :1]).clip(min=0), axis=0)
    times = librosa.frames_to_time(range(len(flux)), sr=sr, hop_length=hop_length)
    
    threshold = np.percentile(flux, threshold_percentile)
    max_flux = np.max(flux) + 1e-8
    
    events = []
    last_event_time = -min_gap_sec
    
    # Find local peaks above threshold
    peak_indices = librosa.util.peak_pick(
        flux,
        pre_max=3, post_max=3, pre_avg=5, post_avg=5,
        delta=threshold * 0.5,
        wait=int(min_gap_sec * sr / hop_length)
    )
    
    for idx in peak_indices:
        t = float(times[idx])
        if t - last_event_time < min_gap_sec:
            continue
        normalized_flux = float(flux[idx] / max_flux)
        score = compute_event_score(6.0, normalized_flux, structural_novelty=normalized_flux)
        events.append({
            "time": t,
            "type": "spectral_flux",
            "weight": 6.0,
            "score": score,
            "transition": "fade",
            "transition_duration": 0.034
        })
        last_event_time = t
    
    return events


def phrase_grouping(events: list[dict], window: float = 1.0) -> list[dict]:
    """
    Groups events within a rolling window (default 1.0s).
    Keeps the highest scoring event in each window, while always preserving Tier 1 events.
    """
    if not events:
        return []
    sorted_ev = sorted(events, key=lambda x: x["time"])
    grouped = []
    
    i = 0
    while i < len(sorted_ev):
        current_ev = sorted_ev[i]
        window_events = [current_ev]
        j = i + 1
        while j < len(sorted_ev) and sorted_ev[j]["time"] - current_ev["time"] <= window:
            window_events.append(sorted_ev[j])
            j += 1
        
        best_ev = max(window_events, key=lambda x: x.get("score", x["weight"]))
        grouped.append(best_ev)
        
        # Preserve other Tier 1 events in this window so they don't get lost
        for ev in window_events:
            if get_event_tier(ev) == 1 and ev is not best_ev:
                grouped.append(ev)
                
        i = j
        
    grouped.sort(key=lambda x: x["time"])
    return grouped


def select_cut_points(
    events: list[dict],
    beat_times: list[float],
    total_duration: float,
    activity_curve: np.ndarray,
    rms_times: np.ndarray,
    tempo_bpm: float,
    sensitivity: str = "medium"
) -> list[dict]:
    
    def get_activity_at_time(t: float) -> float:
        idx = np.searchsorted(rms_times, t)
        idx = min(idx, len(activity_curve) - 1)
        return float(activity_curve[idx])

    beat_duration = 60.0 / max(30.0, tempo_bpm)

    def get_dynamic_gap(current_time: float) -> tuple[float, float]:
        activity = get_activity_at_time(current_time)
        
        # Priority 8: Dynamic BPM Logic
        factor = max(1.0, 3.5 - activity)
        min_gap = beat_duration * factor
        
        # Priority 6: Prevent Machine-Gun Cuts
        if activity < 0.3:
            min_gap = max(1.5, min_gap)
        elif activity < 0.6:
            min_gap = max(1.0, min_gap)
        else:
            min_gap = max(0.4, min_gap)
            
        max_gap = min_gap * 2.5
        return min_gap, max_gap

    cut_points = [{
        "time": 0.0,
        "type": "start",
        "weight": 10.0,
        "transition": "fade",
        "transition_duration": 0.0
    }]
    
    current_time = 0.0
    
    while current_time < total_duration:
        min_gap, max_gap = get_dynamic_gap(current_time)
        
        # Adjust gaps slightly based on sensitivity
        if sensitivity == "tight":
            min_gap *= 0.8
            max_gap *= 0.8
        elif sensitivity == "loose":
            min_gap *= 1.2
            max_gap *= 1.2

        candidate_interval_start = current_time + min_gap
        candidate_interval_end = current_time + max_gap
        
        if candidate_interval_start >= total_duration:
            break
            
        # abs_min_gap: scale with activity to prevent machine-gun cuts
        activity = get_activity_at_time(current_time)
        abs_min_gap = 0.4 if activity < 0.6 else 0.25

        # Find all events falling within the absolute minimum window up to max_gap
        all_window_events = [
            ev for ev in events
            if (current_time + abs_min_gap) <= ev["time"] <= min(candidate_interval_end, total_duration - 0.1)
        ]

        # Priority 1: ALWAYS jump on Tier-1 events (drops, impacts) even if they happen before min_gap
        tier1 = [ev for ev in all_window_events if get_event_tier(ev) == 1]
        if tier1:
            best_event = min(tier1, key=lambda x: x["time"])  # Take the earliest Tier 1 drop
            cut_points.append(best_event)
            current_time = best_event["time"]
            continue

        # Priority 2: Filter to events past the intended min_gap
        interval_events = [ev for ev in all_window_events if ev["time"] >= candidate_interval_start]

        if interval_events:
            best_event = max(interval_events, key=lambda x: x.get("score", x["weight"]))
            cut_points.append(best_event)
            current_time = best_event["time"]
        else:
            # Look for a tempo beat in this interval
            interval_beats = [
                bt for bt in beat_times
                if candidate_interval_start <= bt <= min(candidate_interval_end, total_duration - 0.1)
            ]
            if interval_beats:
                middle = (candidate_interval_start + candidate_interval_end) / 2.0
                best_beat = min(interval_beats, key=lambda x: abs(x - middle))
                cut_points.append({
                    "time": best_beat,
                    "type": "tempo",
                    "weight": 5.0,
                    "score": 10.0,
                    "transition": "fade",
                    "transition_duration": 0.034
                })
                current_time = best_beat
            else:
                forced_time = (candidate_interval_start + min(candidate_interval_end, total_duration - 0.1)) / 2.0
                cut_points.append({
                    "time": forced_time,
                    "type": "force",
                    "weight": 1.0,
                    "score": 2.0,
                    "transition": "fade",
                    "transition_duration": 0.034
                })
                current_time = forced_time

    # Stamp tier onto every selected cut and filter cuts too close to end
    final_cuts = []
    for cp in cut_points:
        if total_duration - cp["time"] > 0.1:
            cp["tier"] = get_event_tier(cp)
            final_cuts.append(cp)

    return final_cuts


def analyze_beats(audio_path: str, sensitivity: str = "medium") -> dict:
    """
    Finds exact transient hits using multi-layer onset detection:
      - Frequency-band transients (kick, snare, bass, vocal, hi-hat)
      - RMS energy rises and falls
      - Spectral flux structural changes
      - Silence detection
      - Drop/impact detection
      - Optional madmom neural onset detection
    Filters cuts to enforce a narrative arc and ranks by composite score.
    """
    print(f"\n🎵 Loading audio: {audio_path}")
    y, sr = librosa.load(audio_path, sr=44100)
    duration = librosa.get_duration(y=y, sr=sr)
    print(f"   Duration: {duration:.1f}s | Sample rate: {sr}Hz")

    # Separate percussion from harmonic content
    print("   Separating percussion and harmonic layers...")
    y_harmonic, y_percussive = librosa.effects.hpss(y, margin=(2.0, 4.0))

    # Get tempo/BPM
    print("   Detecting tempo...")
    tempo, beat_frames = librosa.beat.beat_track(y=y_percussive, sr=sr)
    tempo = float(tempo.item()) if hasattr(tempo, "item") else (float(tempo[0]) if isinstance(tempo, (list, np.ndarray)) else float(tempo))
    print(f"   Tempo: {tempo:.1f} BPM")

    # ─── Layer 1: Band-specific transients (kick, snare, bass, vocal, hi-hat) ─────
    print("   Scanning frequency bands for transients...")
    events = []

    if MADMOM_AVAILABLE:
        print("   [madmom] Running CNN onset detector...")
        try:
            proc = CNNOnsetProcessor()
            act = proc(audio_path)
            madmom_times = np.arange(len(act)) / 100.0
            high_prob = act > 0.5
            for i, (t, p) in enumerate(zip(madmom_times, act)):
                if high_prob[i] and (i == 0 or not high_prob[i-1]):
                    score = compute_event_score(10.0, float(p), energy_jump=float(p) * 0.5)
                    events.append({
                        "time": float(t), "type": "kick",
                        "weight": 10.0 * float(p), "score": score,
                        "transition": "fade", "transition_duration": 0.034
                    })
            print(f"      [madmom] CNN onsets: {sum(1 for e in events if e['type']=='kick')} candidates")
            remaining_layers = {k: v for k, v in EDIT_LAYERS.items() if k not in ("kick", "snare")}
        except Exception as ex:
            print(f"      [madmom] CNN failed ({ex}), falling back to librosa")
            remaining_layers = EDIT_LAYERS
    else:
        remaining_layers = EDIT_LAYERS

    for layer_name, cfg in remaining_layers.items():
        source_y = y_percussive if cfg["source"] == "percussive" else y_harmonic
        times, strengths = detect_band_transients(
            source_y, sr, cfg["low_hz"], cfg["high_hz"],
            hop_length=64, delta=0.1, min_gap_sec=0.08
        )
        for t, s in zip(times, strengths):
            score = compute_event_score(float(cfg["weight"]), float(s))
            events.append({
                "time": float(t), "type": layer_name,
                "weight": float(cfg["weight"]), "score": score,
                "transition": cfg["transition"],
                "transition_duration": float(cfg["transition_duration"])
            })
        print(f"      Band [{layer_name}]: {len(times)} candidates")

    # ─── Layer 2: Onset strength — catches micro-spikes ───────────────
    # vocal consonants, clap hits, hi-hat openings, shutter sounds
    onset_events = detect_onset_strength_events(y, sr)
    events.extend(onset_events)
    print(f"      Onset strength: {len(onset_events)} candidates")

    # ─── Layer 3: Silence detection ──────────────────────────────────
    silences = detect_silences(y, sr, top_db=35)
    for s in silences:
        s["score"] = compute_event_score(s["weight"], 1.0, structural_novelty=0.5)
    events.extend(silences)
    print(f"      Silence-end: {len(silences)} candidates")

    # ─── Layer 4: Drop / impact detection ────────────────────────────
    drops = detect_drops(y, sr)
    events.extend(drops)
    print(f"      Drop/impact: {len(drops)} candidates")

    # ─── Layer 5: RMS gradient rises and falls (Savitzky-Golay) ──────
    rms_events = detect_rms_energy_events(y, sr)
    events.extend(rms_events)
    print(f"      RMS gradient: {len(rms_events)} candidates (rises+falls)")

    # ─── Layer 6: Spectral flux ───────────────────────────────────────
    flux_events = detect_spectral_flux_events(y, sr)
    events.extend(flux_events)
    print(f"      Spectral flux: {len(flux_events)} candidates")

    # ─── Layer 7: Structural novelty (verse→chorus→drop boundaries) ──
    novelty_events = detect_novelty_events(y, y_harmonic, sr)
    events.extend(novelty_events)
    print(f"      Structural novelty: {len(novelty_events)} section boundaries")

    # Shift times 1 frame early for percussive transients to align to attack start
    one_frame = 1.0 / 30.0
    no_shift_types = ("silence_end", "start", "energy_rise", "energy_fall",
                      "spectral_flux", "structural", "onset")
    for ev in events:
        if ev["type"] not in no_shift_types:
            ev["time"] = max(0.0, ev["time"] - one_frame)

    # ─── Climax / Build detection via RMS + Spectral Flux + Onset Density + Novelty ───
    print("   Mapping energy curve & activity curve...")
    try:
        hop_length_map = 512
        # 1. Smoothed RMS
        rms_curve = librosa.feature.rms(y=y, frame_length=2048, hop_length=hop_length_map)[0]
        rms_times = librosa.frames_to_time(range(len(rms_curve)), sr=sr, hop_length=hop_length_map)
        window = max(1, int(0.5 * sr / hop_length_map))  # 0.5s smoothing window
        rms_smooth = np.convolve(rms_curve, np.ones(window)/window, mode='same')
        rms_smooth_norm = rms_smooth / (np.max(rms_smooth) + 1e-8)

        # 2. Smoothed spectral flux
        S = np.abs(librosa.stft(y, hop_length=hop_length_map))
        flux_curve = np.sum(np.diff(S, axis=1, prepend=S[:, :1]).clip(min=0), axis=0)
        flux_smooth = np.convolve(flux_curve, np.ones(window)/window, mode='same')
        if len(flux_smooth) != len(rms_smooth):
            from scipy.interpolate import interp1d
            flux_t = librosa.frames_to_time(range(len(flux_smooth)), sr=sr, hop_length=hop_length_map)
            interp = interp1d(flux_t, flux_smooth, bounds_error=False, fill_value=0)
            flux_smooth = interp(rms_times)
        flux_smooth_norm = flux_smooth / (np.max(flux_smooth) + 1e-8)

        # 3. Onset density
        onset_frames = librosa.onset.onset_detect(y=y, sr=sr, hop_length=hop_length_map)
        onset_times_arr = librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length_map)
        onset_density = np.zeros(len(rms_times))
        window_sec = 1.0
        for i, t in enumerate(rms_times):
            count = np.sum((onset_times_arr >= t - window_sec/2) & (onset_times_arr < t + window_sec/2))
            onset_density[i] = count
        onset_density_norm = onset_density / (np.max(onset_density) + 1e-8)

        # 4. Novelty curve
        try:
            S_mel = librosa.feature.melspectrogram(y=y, sr=sr, hop_length=hop_length_map, n_mels=64)
            log_S_mel = librosa.power_to_db(S_mel)
            C_chroma = librosa.feature.chroma_cqt(y=y_harmonic, sr=sr, hop_length=hop_length_map)
            features = np.vstack([log_S_mel[:12], C_chroma])
            features = librosa.util.normalize(features, axis=1)
            R_novelty = librosa.segment.recurrence_matrix(features, mode='affinity', sym=True)
            lag = librosa.segment.recurrence_to_lag(R_novelty)
            novelty = np.abs(np.diff(lag.diagonal(), prepend=lag.diagonal()[0]))
            novelty_smooth = np.convolve(novelty, np.ones(7)/7, mode='same')
            novelty_smooth_norm = novelty_smooth / (np.max(novelty_smooth) + 1e-8)
            if len(novelty_smooth_norm) != len(rms_smooth_norm):
                from scipy.interpolate import interp1d
                nov_t = librosa.frames_to_time(range(len(novelty_smooth_norm)), sr=sr, hop_length=hop_length_map)
                interp_nov = interp1d(nov_t, novelty_smooth_norm, bounds_error=False, fill_value=0)
                novelty_smooth_norm = interp_nov(rms_times)
        except Exception as nov_ex:
            print(f"      ⚠️ Novelty curve mapping failed ({nov_ex}), using fallback")
            novelty_smooth_norm = np.zeros(len(rms_smooth_norm))

        # 5. Combined Activity Curve
        activity_curve = (
            rms_smooth_norm * 0.35
            + onset_density_norm * 0.30
            + flux_smooth_norm * 0.20
            + novelty_smooth_norm * 0.15
        )

        combined = rms_smooth_norm + flux_smooth_norm + onset_density_norm
        climax_frame = int(np.argmax(combined))
        climax_time = float(rms_times[climax_frame])

        pre_climax_combined = combined[:climax_frame] if climax_frame > 0 else combined
        if len(pre_climax_combined) > 0:
            diff_combined = np.diff(pre_climax_combined, prepend=pre_climax_combined[0])
            build_frame = int(np.argmax(diff_combined))
            drop_time = float(rms_times[build_frame])
        else:
            drop_time = duration * 0.3

    except Exception as e:
        print(f"   ⚠️  Energy map / activity curve failed ({e}), using defaults")
        hop_length_map = 512
        rms_times = np.linspace(0, duration, num=100)
        activity_curve = np.ones(len(rms_times)) * 0.5
        climax_time = duration * 0.7
        drop_time = duration * 0.3

    print(f"   Climax at: {climax_time:.2f}s | Build at: {drop_time:.2f}s")

    # ─── Priority 3: Event-Type Multipliers ───
    for ev in events:
        ev["score"] = ev.get("score", ev["weight"]) * EVENT_MULTIPLIERS.get(ev["type"], 1.0)

    # ─── Priority 7: Score Boosting (Proximity Agreement) ───
    for ev in events:
        nearby_types = {
            other["type"] for other in events
            if abs(other["time"] - ev["time"]) <= 0.1 and other is not ev
        }
        boost = 0.0
        if ev["type"] == "kick" and "spectral_flux" in nearby_types:
            boost += 15.0
        elif ev["type"] == "spectral_flux" and "kick" in nearby_types:
            boost += 15.0

        if ev["type"] == "vocal" and "energy_rise" in nearby_types:
            boost += 10.0
        elif ev["type"] == "energy_rise" and "vocal" in nearby_types:
            boost += 10.0

        if ev["type"] == "drop" and "structural" in nearby_types:
            boost += 25.0
        elif ev["type"] == "structural" and "drop" in nearby_types:
            boost += 25.0

        if len(nearby_types) >= 2:
            boost += len(nearby_types) * 5.0

        ev["score"] += boost

    # Merge close hits within 50ms
    merged_events = merge_and_resolve_events(events, min_gap_sec=0.05)
    print(f"   Merged candidates: {len(merged_events)}")

    # ─── Priority 5: Phrase Grouping ───
    grouped_events = phrase_grouping(merged_events, window=1.0)
    print(f"   Phrase grouped candidates: {len(grouped_events)}")

    # ─── Priority 4: Adaptive Cut Budget ───
    avg_activity = float(np.mean(activity_curve))
    target_cuts = int(duration * (0.4 + avg_activity))
    target_cuts = max(10, min(target_cuts, 100))  # bounds to keep it reasonable
    
    critical_types = {"start", "drop", "structural"}
    critical_events = [ev for ev in grouped_events if ev["type"] in critical_types]
    other_events = [ev for ev in grouped_events if ev["type"] not in critical_types]
    other_events.sort(key=lambda x: x.get("score", x["weight"]), reverse=True)
    allowed_others_count = max(0, target_cuts - len(critical_events))
    
    budgeted_events = critical_events + other_events[:allowed_others_count]
    budgeted_events.sort(key=lambda x: x["time"])
    print(f"   Budgeted to: {len(budgeted_events)} events (target was {target_cuts}, critical was {len(critical_events)})")

    # Beat times for fallback
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()

    # Select cuts using the new Dynamic Density selection engine
    selected_cuts = select_cut_points(
        budgeted_events, beat_times, duration,
        activity_curve, rms_times, tempo,
        sensitivity=sensitivity
    )
    
    cut_times = [cp["time"] for cp in selected_cuts]
    avg_clip_duration = duration / len(selected_cuts) if selected_cuts else 3.0

    print(f"   Filtered to {len(selected_cuts)} cut points")
    print(f"   Avg clip duration: {avg_clip_duration:.2f}s")

    return {
        "tempo_bpm": tempo,
        "duration": duration,
        "beat_times": beat_times,
        "cut_points": cut_times,
        "cut_details": selected_cuts,
        "avg_clip_duration": avg_clip_duration,
        "narrative_anchors": {
            "hook_start":   0.0,
            "build_start":  drop_time,
            "climax_start": climax_time,
            "payoff_start": climax_time + (duration - climax_time) * 0.5,
            "total_duration": duration
        }
    }


# ─────────────────────────────────────────────
# STEP 2: Motion Detection (Trimming Dead Frames)
# ─────────────────────────────────────────────

def find_first_motion_frame(clip_path: str) -> float:
    """
    Scans the first 2 seconds of a clip to find when actual motion starts
    using FFmpeg's freezedetect filter.
    """
    cmd = [
        "ffmpeg", "-y",
        "-i", clip_path,
        "-t", "2",
        "-vf", "freezedetect=noise=0.003:duration=0.1,metadata=print",
        "-an",
        "-f", "null", "-"
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)

    freeze_end = 0.0
    for line in result.stderr.split('\n'):
        if 'freeze_end' in line:
            try:
                parts = line.split('freeze_end:')
                if len(parts) > 1:
                    freeze_end = float(parts[1].split()[0].strip())
            except Exception:
                pass

    return max(0.0, freeze_end + (1.0 / 30.0))


# ─────────────────────────────────────────────
# STEP 3: Assign Clips to Windows
# ─────────────────────────────────────────────

def assign_clips_to_beats(clip_paths: list[str], beat_data: dict) -> list[dict]:
    """
    Maps each available clip to a transient window.
    Uses a SHUFFLED playlist so every cut gets a maximally different clip:
      - All clips are shuffled randomly before assignment.
      - Back-to-back repeats are NEVER allowed.
      - EVERY single cut point advances to a new clip (no visual-only reused clips).
    """
    import random

    cut_points = beat_data["cut_points"]
    cut_details = beat_data.get("cut_details", [])
    total_duration = beat_data["duration"]

    windows = []
    for i, start in enumerate(cut_points):
        end = cut_points[i + 1] if i + 1 < len(cut_points) else total_duration
        windows.append((start, end))

    print(f"\n📋 Assigning {len(clip_paths)} clips to {len(windows)} windows (shuffled, no-repeat)...")

    def build_shuffled_playlist(clips: list[str], last_clip: str | None = None) -> list[str]:
        pool = clips[:]
        random.shuffle(pool)
        if last_clip and len(pool) > 1 and pool[0] == last_clip:
            pool[0], pool[1] = pool[1], pool[0]
        return pool

    playlist = build_shuffled_playlist(clip_paths)
    playlist_pos = 0
    last_used_clip = None

    assignments = []

    for i, (start, end) in enumerate(windows):
        duration_needed = end - start

        transition = "fade"
        transition_duration = 0.034
        tier = 1
        event_type = "start"
        score = 10.0

        if i < len(cut_details):
            detail = cut_details[i]
            transition = detail.get("transition", "fade")
            transition_duration = detail.get("transition_duration", 0.034)
            tier = detail.get("tier", get_event_tier(detail))
            event_type = detail.get("type", "start")
            score = detail.get("score", detail.get("weight", 10.0))

        # ALWAYS advance to next clip in shuffled playlist
        if playlist_pos >= len(playlist):
            playlist = build_shuffled_playlist(clip_paths, last_clip=last_used_clip)
            playlist_pos = 0

        clip = playlist[playlist_pos]

        if clip == last_used_clip and len(playlist) > 1:
            swap_idx = (playlist_pos + 1) % len(playlist)
            playlist[playlist_pos], playlist[swap_idx] = playlist[swap_idx], playlist[playlist_pos]
            clip = playlist[playlist_pos]

        last_used_clip = clip
        playlist_pos += 1
        effect = "cut"

        assignments.append({
            "clip_path":           clip,
            "music_start":         round(start, 4),
            "music_end":           round(end, 4),
            "clip_duration":       round(duration_needed, 4),
            "window_index":        i,
            "transition":          transition,
            "transition_duration": transition_duration,
            "tier":                tier,
            "effect":              effect,
            "event_type":          event_type,
            "score":               round(score, 2)
        })

    cuts = sum(1 for a in assignments if a["effect"] == "cut")
    effects = sum(1 for a in assignments if a["effect"] != "cut")
    print(f"   ✅ {len(assignments)} segments | {cuts} clip cuts | {effects} visual-only effects")
    return assignments


# ─────────────────────────────────────────────
# STEP 4: FFmpeg Stitch with xfade
# ─────────────────────────────────────────────

def stitch_with_ffmpeg(
    assignments: list[dict],
    audio_path: str,
    output_path: str,
    transition: str = "fade",
    transition_duration: float = 0.1,
    zoom: bool = False
) -> str:
    """
    Stitches clips together using FFmpeg, aligned to exact transient offsets.
    """

    print(f"\n🎬 Building FFmpeg command...")
    print(f"   Clips: {len(assignments)} | Transition: {transition} ({transition_duration}s) | Zoom: {zoom}")

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

    with tempfile.TemporaryDirectory() as tmpdir:

        # ── Step A: Transcode to CFR + trim dead frames + scale ──
        trimmed = []
        actual_durations = []
        for i, seg in enumerate(assignments):
            # First convert raw clip to CFR
            cfr_path = os.path.join(tmpdir, f"cfr_{i:04d}.mp4")
            transcode_to_cfr(seg["clip_path"], cfr_path, fps=30)

            # Skip dead frames
            motion_start = find_first_motion_frame(cfr_path)
            duration = seg["clip_duration"]
            if motion_start > 0.0:
                print(f"   🎬 Detected static/frozen header: skipping first {motion_start:.2f}s of motion")

            # Trim CFR clip to transient window
            trimmed_path = os.path.join(tmpdir, f"seg_{i:04d}.mp4")
            
            vf_filters = [
                "scale=1080:1920:force_original_aspect_ratio=decrease",
                "pad=1080:1920:(ow-iw)/2:(oh-ih)/2",
                "fps=fps=30",
                "format=yuv420p"
            ]
            
            if zoom:
                fps = 30
                zoom_duration = 0.12
                zoom_intensity = 1.08
                zoom_frames = int(zoom_duration * fps)
                vf_filters.append(
                    f"zoompan=z='if(lte(on,{zoom_frames}),{zoom_intensity}-({zoom_intensity}-1)*on/{zoom_frames},1)':"
                    f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:fps={fps}:s=1080x1920"
                )

            cmd = [
                "ffmpeg", "-y",
                "-ss", str(motion_start),      # seek to actual motion start
                "-i", cfr_path,
                "-t", str(duration),          # trim to exact window length
                "-an",                         # mute clip audio
                "-vf", ",".join(vf_filters),   # Force consistent pixel format and optional zoom
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",         # Force consistent pixel format
                "-video_track_timescale", "15360", # Force consistent timebase
                "-preset", "fast",
                "-crf", "23",
                trimmed_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                print(f"   ⚠️  Clip {i} failed: {result.stderr[-200:]}")
                continue
                
            actual_dur = get_actual_duration(trimmed_path)
            if actual_dur <= 0.0:
                print(f"   ⚠️  Trimmed clip {i} is empty or invalid. Skipping.")
                continue
                
            trimmed.append(trimmed_path)
            actual_durations.append(actual_dur)
            print(f"   Trimmed clip {i+1}/{len(assignments)}: actual={actual_dur:.2f}s (requested={duration:.2f}s)")

        if not trimmed:
            raise RuntimeError("No clips were trimmed successfully. Check your clip paths.")

        # ── Step B: Chain xfade filters in chunks to avoid OS thread/file limits ──
        clips_info = []
        for i in range(len(trimmed)):
            clips_info.append({
                "path": trimmed[i],
                "duration": actual_durations[i],
                "transition": assignments[i].get("transition", transition),
                "transition_duration": assignments[i].get("transition_duration", transition_duration)
            })

        BATCH_SIZE = 40
        round_idx = 0
        
        while len(clips_info) > 1:
            next_clips_info = []
            for i in range(0, len(clips_info), BATCH_SIZE):
                batch = clips_info[i : i + BATCH_SIZE]
                if len(batch) == 1:
                    next_clips_info.append(batch[0])
                    continue

                batch_out = os.path.join(tmpdir, f"batch_{round_idx}_{len(next_clips_info)}.mp4")
                inputs = []
                for c in batch:
                    inputs += ["-i", c["path"]]

                filter_parts = []
                current_label = "[0:v]"
                accumulated_duration = batch[0]["duration"]
                last_transition_end = 0.0

                for j in range(1, len(batch)):
                    trans_type = batch[j]["transition"]
                    trans_dur = batch[j]["transition_duration"]
                    offset = accumulated_duration - trans_dur
                    offset = max(last_transition_end, offset - 0.001)

                    out_label = f"[vx{j}]"
                    filter_parts.append(
                        f"{current_label}[{j}:v]xfade="
                        f"transition={trans_type}:"
                        f"duration={trans_dur}:"
                        f"offset={offset:.4f}"
                        f"{out_label}"
                    )
                    accumulated_duration = offset + batch[j]["duration"]
                    last_transition_end = offset + trans_dur
                    current_label = out_label

                filter_str = ";".join(filter_parts)

                cmd = (
                    ["ffmpeg", "-y"] + inputs +
                    [
                        "-filter_complex", filter_str,
                        "-map", current_label,
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-crf", "23",
                        batch_out
                    ]
                )
                print(f"   🎬 Stitching chunk of {len(batch)} clips...")
                res = subprocess.run(cmd, capture_output=True, text=True)
                if res.returncode != 0:
                    raise RuntimeError(f"FFmpeg chunk xfade failed:\n{res.stderr}")

                actual_dur = get_actual_duration(batch_out)
                next_clips_info.append({
                    "path": batch_out,
                    "duration": actual_dur,
                    # Preserve the transition properties of the first clip in this batch
                    # so when this batch is merged with the previous batch, it uses the correct transition.
                    "transition": batch[0]["transition"],
                    "transition_duration": batch[0]["transition_duration"]
                })
            clips_info = next_clips_info
            round_idx += 1

        concat_path = clips_info[0]["path"]

        # ── Step C: Mux BGM audio track ──
        print("   Muxing BGM audio track...")
        cmd = [
            "ffmpeg", "-y",
            "-i", concat_path,
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg mux failed:\n{result.stderr[-500:]}")

    print(f"\n✅ Output saved: {output_path}")
    return output_path


# ─────────────────────────────────────────────
# Debug Save
# ─────────────────────────────────────────────

def save_analysis(beat_data: dict, output_dir: str):
    path = os.path.join(output_dir, "beat_analysis.json")
    with open(path, "w") as f:
        json.dump(beat_data, f, indent=2)
    print(f"\n📊 Beat analysis saved: {path}")


def generate_waveform_chart(audio_path: str, beat_data: dict, output_chart_path: str):
    """
    Generates a professional DAW-style stereo waveform with COLOR-CODED vertical cut lines.
    Each event type gets a distinct color so you can instantly see WHY the cut was chosen.

    Color Legend:
      RED     (#FF3B30) = Drop / impact
      ORANGE  (#FF9500) = Energy rise
      MAGENTA (#FF2D55) = Energy fall
      PURPLE  (#BF5AF2) = Spectral flux / structural change
      CYAN    (#5AC8FA) = Silence end / attack
      YELLOW  (#FFD60A) = Kick drum
      GREEN   (#30D158) = Snare
      AMBER   (#FF6B35) = Bass hit
      BLUE    (#0A84FF) = Vocal attack
      WHITE   (#E0E0E0) = Hi-hat
      GRAY    (#636366) = Tempo grid fallback
    """
    print(f"\n📊 Generating waveform visualization chart...")
    try:
        import matplotlib.pyplot as plt
        import matplotlib.patches as mpatches
    except ImportError:
        print("   ⚠️  matplotlib is not installed. Skipping chart. Run: pip install matplotlib")
        return

    try:
        # Load audio (stereo if available)
        y, sr = librosa.load(audio_path, sr=None, mono=False)
        duration = librosa.get_duration(y=y, sr=sr)
        time_axis = np.linspace(0, duration, num=y.shape[-1] if len(y.shape) > 1 else len(y))

        cut_details = beat_data.get("cut_details", [])

        # ── DAW dark theme ──────────────────────────────────────────────
        BG      = '#0A0A0A'
        WAVE_L  = '#4EC9B0'   # Left channel  — teal
        WAVE_R  = '#9CDCFE'   # Right channel — sky blue
        GRID    = '#1E1E1E'
        
        plt.rcParams.update({
            'figure.facecolor':  BG,
            'axes.facecolor':    BG,
            'text.color':        '#D4D4D4',
            'axes.labelcolor':   '#D4D4D4',
            'xtick.color':       '#666666',
            'ytick.color':       '#666666',
            'grid.color':        GRID,
            'axes.spines.left':  True,
            'axes.spines.right': False,
            'axes.spines.top':   False,
            'axes.edgecolor':    '#333333',
            'agg.path.chunksize': 10000,
        })

        # ── Figure layout: waveform (top 2/3) + legend strip (bottom) ──
        fig = plt.figure(figsize=(22, 11), facecolor=BG)
        gs  = fig.add_gridspec(3, 1, height_ratios=[4, 4, 1.2], hspace=0.05)
        ax_L = fig.add_subplot(gs[0])
        ax_R = fig.add_subplot(gs[1], sharex=ax_L)
        ax_leg = fig.add_subplot(gs[2])
        ax_leg.axis('off')

        # Split channels
        if len(y.shape) == 1:
            y_left = y
            y_right = y
        else:
            y_left  = y[0]
            y_right = y[1]

        # ── Plot waveforms ──────────────────────────────────────────────
        
        # Downsample massive arrays to avoid Matplotlib OverflowError on long songs
        MAX_POINTS = 200_000
        if len(time_axis) > MAX_POINTS:
            ds = len(time_axis) // MAX_POINTS
            time_axis = time_axis[::ds]
            y_left = y_left[::ds]
            y_right = y_right[::ds]

        ax_L.fill_between(time_axis, y_left,  0, color=WAVE_L, alpha=0.6, linewidth=0)
        ax_L.plot(time_axis, y_left,  color=WAVE_L, linewidth=0.3, alpha=0.9)
        ax_L.set_ylabel("L", color='#888888', fontsize=10, rotation=0, labelpad=10)
        ax_L.set_ylim(-1.15, 1.45)   # extra headroom for labels
        ax_L.grid(True, linestyle='-', linewidth=0.4)
        ax_L.tick_params(labelbottom=False)

        ax_R.fill_between(time_axis, y_right, 0, color=WAVE_R, alpha=0.6, linewidth=0)
        ax_R.plot(time_axis, y_right, color=WAVE_R, linewidth=0.3, alpha=0.9)
        ax_R.set_ylabel("R", color='#888888', fontsize=10, rotation=0, labelpad=10)
        ax_R.set_ylim(-1.15, 1.45)
        ax_R.grid(True, linestyle='-', linewidth=0.4)
        ax_R.set_xlabel("Time (seconds)", color='#D4D4D4', fontsize=12)

        # ── Draw color-coded cut lines ──────────────────────────────────
        label_y_top     = 1.25   # label position in ax_L
        label_y_bottom  = 1.25   # label position in ax_R
        label_alternating = True  # alternate label height to reduce overlap
        label_flip = False

        seen_types = set()
        for cut in cut_details:
            t = cut["time"]
            if t <= 0.0:
                continue

            event_type = cut.get("type", "force")
            color = EVENT_COLORS.get(event_type, "#636366")
            score = cut.get("score", cut.get("weight", 0.0))

            # Line weight scales with score (more important = thicker)
            lw = 1.0 + min(score / 60.0, 1.5)

            ax_L.axvline(x=t, color=color, linestyle='-', linewidth=lw, alpha=0.92)
            ax_R.axvline(x=t, color=color, linestyle='-', linewidth=lw, alpha=0.92)

            # Label only on top waveform, alternate height
            y_label = label_y_top if not label_flip else 1.10
            short_type = event_type.replace('_', ' ').replace('spectral flux', 'S.FLUX')[:8].upper()
            ax_L.text(
                t, y_label,
                f"{short_type}\n{t:.2f}s",
                color=color, fontsize=6.5,
                ha='center', va='bottom',
                fontweight='bold',
                bbox=dict(facecolor=BG, edgecolor='none', pad=1.5, alpha=0.85)
            )
            label_flip = not label_flip
            seen_types.add(event_type)

        # ── Legend strip ────────────────────────────────────────────────
        legend_handles = []
        for etype in sorted(seen_types):
            col = EVENT_COLORS.get(etype, '#636366')
            patch = mpatches.Patch(color=col, label=etype.replace('_', ' ').title())
            legend_handles.append(patch)
        if legend_handles:
            ax_leg.legend(
                handles=legend_handles,
                loc='center', ncol=min(len(legend_handles), 7),
                fontsize=9, frameon=False,
                labelcolor='#D4D4D4'
            )

        # ── Title ────────────────────────────────────────────────────────
        audio_name = Path(audio_path).stem
        n_cuts = len([c for c in cut_details if c["time"] > 0])
        fig.suptitle(
            f"Beat Sync Analysis — {audio_name}   |   {n_cuts} cuts   |   {beat_data.get('tempo_bpm', 0):.1f} BPM",
            color='#D4D4D4', fontsize=13, fontweight='bold', y=0.98
        )

        plt.xlim(0, duration)

        # Ensure output directory exists and save
        os.makedirs(os.path.dirname(os.path.abspath(output_chart_path)), exist_ok=True)
        plt.savefig(output_chart_path, dpi=200, bbox_inches='tight',
                    facecolor=fig.get_facecolor(), edgecolor='none')
        plt.close(fig)
        print(f"   ✅ Color-coded waveform chart saved: {output_chart_path}")
    except Exception as e:
        import traceback
        print(f"   ⚠️  Failed to generate waveform chart: {e}")
        traceback.print_exc()


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Beat-sync video test — instrumental tracks")
    parser.add_argument("--audio",      required=True, help="Path to instrumental MP3/WAV")
    parser.add_argument("--clips_dir",  required=True, help="Directory containing your video clips (.mp4)")
    parser.add_argument("--output",     default="beat_sync_output.mp4", help="Output file path")
    parser.add_argument("--sensitivity",default="medium", choices=["tight", "medium", "loose"],
                        help="tight=fast cuts | medium=balanced | loose=slow cinematic cuts")
    parser.add_argument("--transition", default="fade",
                        help="xfade transition type: fade|wipeleft|dissolve|slideleft")
    parser.add_argument("--max_clips",  type=int, default=None,
                        help="Limit how many clips to use (for quick testing)")
    parser.add_argument("--zoom",       action="store_true", help="Add zoom punch animation on each cut point")
    args = parser.parse_args()

    clips_dir = Path(args.clips_dir)
    clip_paths = sorted([
        str(p) for p in clips_dir.rglob("*") if p.suffix.lower() in [".mp4", ".mov"]
    ])
    if not clip_paths:
        print(f"❌ No .mp4 clips found in {args.clips_dir}")
        return

    if args.max_clips:
        clip_paths = clip_paths[:args.max_clips]

    print(f"📁 Found {len(clip_paths)} clips")

    beat_data   = analyze_beats(args.audio, sensitivity=args.sensitivity)
    assignments = assign_clips_to_beats(clip_paths, beat_data)
    output_path = stitch_with_ffmpeg(
        assignments,
        audio_path=args.audio,
        output_path=args.output,
        transition=args.transition,
        transition_duration=0.08,
        zoom=args.zoom
    )

    save_analysis(beat_data, str(Path(args.output).parent))

    # Generate waveform chart dynamically next to output video
    output_base = os.path.splitext(args.output)[0]
    chart_path = f"{output_base}_waveform.png"
    generate_waveform_chart(args.audio, beat_data, chart_path)

    print("\n" + "="*50)
    print("ACCURATE BEAT SYNC SUMMARY (CFR + TRANSIENT RESOLUTION)")
    print("="*50)
    print(f"  Tempo:          {beat_data['tempo_bpm']:.1f} BPM")
    print(f"  Cut points:     {len(beat_data['cut_points'])}")
    print(f"  Avg clip dur:   {beat_data['avg_clip_duration']:.2f}s")
    print(f"  Climax at:      {beat_data['narrative_anchors']['climax_start']:.2f}s")
    print(f"  Output:         {output_path}")
    print("="*50)


if __name__ == "__main__":
    main()
