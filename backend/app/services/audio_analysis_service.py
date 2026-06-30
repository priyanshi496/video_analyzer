import os
import logging
import librosa
import numpy as np

logger = logging.getLogger(__name__)

def get_local_hookline_start(audio_path: str) -> float:
    """
    Analyzes the local audio file to find the start of the hookline/chorus.
    It does this by calculating the smoothed RMS energy across the track 
    and finding the peak sustained loud section.

    Returns 0.0 as a safe fallback if it fails.
    """
    if not os.path.exists(audio_path):
        logger.warning(f"[Librosa] Audio file not found at {audio_path}. Falling back to 0.0.")
        return 0.0

    try:
        logger.info(f"[Librosa] Analyzing {audio_path} for hookline...")
        # Load audio (resample to 22050 Hz for speed)
        # Using a shorter duration (e.g. first 2 minutes) can speed this up, 
        # but full song is safer to find the true climax.
        y, sr = librosa.load(audio_path, sr=22050, mono=True)
        
        # Calculate RMS energy
        rms = librosa.feature.rms(y=y)[0]
        
        # Smooth the RMS to find sustained loud sections instead of short peaks (e.g., drum hits)
        # Using a moving average of about 2 seconds
        # default hop_length is 512, so sr/512 frames per second
        frames_per_sec = sr / 512.0
        window_size = int(frames_per_sec * 2.0)
        
        if window_size > 0 and len(rms) > window_size:
            # Box filter for moving average
            smoothed_rms = np.convolve(rms, np.ones(window_size)/window_size, mode='same')
        else:
            smoothed_rms = rms
            
        # Find the frame index of the maximum smoothed energy
        peak_frame = np.argmax(smoothed_rms)
        
        # Convert frame index to time in seconds
        peak_time = librosa.frames_to_time(peak_frame, sr=sr)
        
        # We don't want the absolute end of the song to be the "hook"
        # If the peak is in the last 15 seconds, let's just use 0.0
        duration = librosa.get_duration(y=y, sr=sr)
        if peak_time > duration - 15.0:
            logger.info(f"[Librosa] Peak time {peak_time:.1f}s is too close to end of song (duration={duration:.1f}s). Falling back to 0.0.")
            return 0.0
            
        logger.info(f"[Librosa] Hookline detected at {peak_time:.1f}s")
        return float(peak_time)
        
    except Exception as e:
        logger.warning(f"[Librosa] Hookline detection failed for {audio_path}: {e}. Falling back to 0.0.")
        return 0.0
