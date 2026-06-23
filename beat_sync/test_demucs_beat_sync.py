import os
import sys
import subprocess
import logging
import random
from pathlib import Path

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

def run_demucs(audio_path: str, output_dir: str) -> str:
    """
    Run Demucs to separate the drum stem from the audio file.
    """
    logger.info(f"Running Demucs on {audio_path}...")
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "--two-stems=drums",
        "-n", "htdemucs",
        "-o", output_dir,
        audio_path
    ]
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as e:
        logger.error(f"Demucs failed: {e}")
        raise

    base_name = Path(audio_path).stem
    drums_path = Path(output_dir) / "htdemucs" / base_name / "drums.wav"
    
    if not drums_path.exists():
        raise FileNotFoundError(f"Expected Demucs output not found at {drums_path}")
        
    return str(drums_path)

def extract_beats_librosa(audio_path: str) -> list[float]:
    """
    Extract beat times using librosa.
    """
    import librosa
    import numpy as np
    from scipy.signal import find_peaks

    logger.info(f"Analyzing major beats from pure energy spikes in {audio_path}...")
    
    y, sr = librosa.load(audio_path, sr=22050)
    
    # Calculate the onset strength (energy envelope)
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    
    # Normalize the energy envelope to 0.0 - 1.0
    if np.max(onset_env) > 0:
        onset_env = onset_env / np.max(onset_env)
        
    # Minimum spacing of 1.2 seconds between major beats
    min_dist_frames = int(1.2 * sr / 512)
    
    # Find exact frames of the biggest energy spikes
    # Prominence of 0.35 means it must be a significant isolated jump in energy
    peaks, _ = find_peaks(onset_env, prominence=0.35, distance=min_dist_frames)
    
    # If it didn't find enough, lower the threshold a bit
    if len(peaks) < 5:
        peaks, _ = find_peaks(onset_env, prominence=0.2, distance=min_dist_frames)
    
    beat_times = librosa.frames_to_time(peaks, sr=sr)
    logger.info(f"Detected {len(beat_times)} MAJOR beats directly from energy spikes.")
    
    return list(beat_times)

def create_beat_synced_video(audio_path: str, video_paths: list, beat_times: list[float], output_video: str):
    """
    Builds a video synced to the beats using ffmpeg-python.
    Cycles through a list of videos on each beat.
    """
    try:
        import ffmpeg
    except ImportError:
        logger.error("ffmpeg-python not found! Please run: pip install ffmpeg-python")
        sys.exit(1)
        
    logger.info("Building video using FFmpeg...")
    
    # Get audio duration
    try:
        probe_a = ffmpeg.probe(audio_path)
        audio_info = next(s for s in probe_a['streams'] if s['codec_type'] == 'audio')
        audio_dur = float(audio_info['duration'])
    except:
        audio_dur = beat_times[-1] + 5.0

    # Add a start at 0.0 if not present
    if len(beat_times) > 0 and beat_times[0] > 0.1:
        beat_times = [0.0] + beat_times
        
    # Add the end of the audio as the last beat so it goes until the end
    beat_times.append(audio_dur)

    video_streams = []
    
    # Set a target resolution and fps so concatenation works perfectly
    # even if the 3 source videos have completely different sizes.
    TARGET_WIDTH = 1080
    TARGET_HEIGHT = 1920
    TARGET_FPS = 30

    logger.info(f"Slicing videos into {len(beat_times)-1} segments based on beats...")
    for i in range(len(beat_times) - 1):
        start_t = beat_times[i]
        end_t = beat_times[i+1]
        duration = end_t - start_t
        
        if duration <= 0:
            continue
            
        current_video = video_paths[i % len(video_paths)]
        
        # Always start at the beginning of the video for each beat
        start_point = 0
            
        # Extract the repeating subclip
        clip = ffmpeg.input(current_video, ss=start_point, t=duration).video
        
        # Scale and pad the clip to exactly the target resolution so FFmpeg concat doesn't fail
        clip = clip.filter('scale', TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio='decrease')
        clip = clip.filter('pad', TARGET_WIDTH, TARGET_HEIGHT, '(ow-iw)/2', '(oh-ih)/2')
        clip = clip.filter('fps', fps=TARGET_FPS, round='up')
        clip = clip.filter('format', 'yuv420p')

        video_streams.append(clip)

    logger.info("Concatenating clips and rendering...")
    # Concat all video streams
    joined_video = ffmpeg.concat(*video_streams, v=1, a=0)
    
    # Load original audio
    audio_stream = ffmpeg.input(audio_path).audio
    
    # Output
    out = ffmpeg.output(joined_video, audio_stream, output_video, vcodec="libx264", acodec="aac", shortest=None)
    
    try:
        # Run FFmpeg (overwrite if exists, hide noisy output)
        out.run(overwrite_output=True, capture_stdout=True, capture_stderr=True)
    except ffmpeg.Error as e:
        logger.error("FFmpeg error occurred!")
        logger.error(e.stderr.decode('utf-8'))
        raise

if __name__ == "__main__":
    # Default paths so you don't have to type them every time
    default_audio = "/Users/tsc/Desktop/video_analyzer/WhatsApp Audio 2026-06-22 at 11.01.36 AM.mpeg"
    
    # We now take a list of videos to cycle through!
    default_videos = [
        "/Users/tsc/Desktop/video_analyzer/salangpur1.mp4",
        "/Users/tsc/Desktop/video_analyzer/trip2 (1).mp4",
        "/Users/tsc/Desktop/video_analyzer/salangpur3.mp4"
    ]

    if len(sys.argv) >= 3:
        audio_file = sys.argv[1]
        # Allow multiple videos from command line args too
        video_files = sys.argv[2:]
    else:
        logger.info("Using default hardcoded paths for audio and 3 videos...")
        audio_file = default_audio
        video_files = default_videos
    
    output_dir = "demucs_output"
    Path(output_dir).mkdir(exist_ok=True)
    
    try:
        # 1. Isolate Drums using Demucs
        drum_stem_path = run_demucs(audio_file, output_dir)
        
        # 2. Extract Beats from the Drum stem using Librosa
        beats = extract_beats_librosa(drum_stem_path)
        
        # 3. Create a synced video using FFmpeg
        out_video = "synced_output_ffmpeg.mp4"
        create_beat_synced_video(audio_file, video_files, beats, out_video)
        
        print(f"\n--- SUCCESS! ---")
        print(f"Your beat synced video has been saved to: {out_video}")
        
    except Exception as e:
        logger.error(f"Error occurred: {e}")
