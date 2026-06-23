import librosa
import librosa.display
import matplotlib.pyplot as plt
import numpy as np
from scipy.signal import find_peaks
import sys
import os

def plot_audio_analysis(audio_file, output_image="beats_visualization.png"):
    print(f"Loading {audio_file}...")
    y, sr = librosa.load(audio_file)
    
    print("Extracting energy spikes (beats)...")
    onset_env = librosa.onset.onset_strength(y=y, sr=sr)
    if np.max(onset_env) > 0:
        onset_env = onset_env / np.max(onset_env)
        
    min_dist_frames = int(0.8 * sr / 512)
    peaks, _ = find_peaks(onset_env, prominence=0.35, distance=min_dist_frames)
    if len(peaks) < 5:
        peaks, _ = find_peaks(onset_env, prominence=0.2, distance=min_dist_frames)
    
    beat_times = librosa.frames_to_time(peaks, sr=sr)
    
    print(f"Detected {len(beat_times)} major beats. Plotting...")
    fig, ax = plt.subplots(nrows=3, figsize=(14, 10), sharex=True)
    
    # --- GRAPH 1: Waveform ---
    librosa.display.waveshow(y, sr=sr, ax=ax[0], alpha=0.6)
    ax[0].vlines(beat_times, -1, 1, color='r', alpha=0.8, linestyle='--', label='Cuts (Beats)')
    ax[0].set(title='Audio Waveform with Final Cut Points')
    ax[0].legend()
    ax[0].label_outer()

    # --- GRAPH 2: Energy Envelope ---
    times = librosa.frames_to_time(np.arange(len(onset_env)), sr=sr)
    ax[1].plot(times, onset_env, label='Onset Strength (Energy)')
    ax[1].vlines(beat_times, 0, 1, color='r', alpha=0.8, linestyle='--')
    ax[1].plot(times[peaks], onset_env[peaks], 'ro')
    ax[1].set(title='Energy Map & Peak Detection')
    ax[1].legend()
    ax[1].label_outer()

    # --- GRAPH 3: Spectrogram ---
    S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=128)
    S_dB = librosa.power_to_db(S, ref=np.max)
    img = librosa.display.specshow(S_dB, x_axis='time', y_axis='mel', sr=sr, ax=ax[2])
    fig.colorbar(img, ax=ax[2], format='%+2.0f dB')
    
    # We only draw vertical lines for beats (y-axis is mel frequency bands)
    ax[2].vlines(beat_times, 0, 8192, color='r', alpha=0.8, linestyle='--')
    ax[2].set(title='Mel-frequency Spectrogram')

    plt.tight_layout()
    # Save the output
    abs_output = os.path.abspath(output_image)
    plt.savefig(abs_output)
    print(f"Saved graph to {abs_output}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python plot_beats.py <audio_file>")
        sys.exit(1)
        
    audio_path = sys.argv[1]
    plot_audio_analysis(audio_path, "beats_visualization.png")
