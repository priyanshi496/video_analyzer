import librosa
import numpy as np
import matplotlib.pyplot as plt
import json
import os

# Paths configuration
analysis_path = "beat_analysis.json"
audio_path = "../projects/my-reel/audio_cache/vacation.mp3"
output_path = "/Users/priyanshimodi/.gemini/antigravity-ide/brain/81d67246-4a71-4794-8272-906ffd3f5bfa/waveform_cuts.png"

# Read analysis data
with open(analysis_path, "r") as f:
    beat_data = json.load(f)

cut_details = beat_data["cut_details"]

# Load BGM track
print(f"Loading {audio_path}...")
y, sr = librosa.load(audio_path, sr=None, mono=False)
duration = librosa.get_duration(y=y, sr=sr)
time_axis = np.linspace(0, duration, num=y.shape[-1] if len(y.shape) > 1 else len(y))

# Configure style (Match the dark mode DAW screenshot)
plt.rcParams['figure.facecolor'] = '#050505'
plt.rcParams['axes.facecolor'] = '#050505'
plt.rcParams['text.color'] = '#ffffff'
plt.rcParams['axes.labelcolor'] = '#ffffff'
plt.rcParams['xtick.color'] = '#888888'
plt.rcParams['ytick.color'] = '#888888'
plt.rcParams['grid.color'] = '#181818'

fig, axes = plt.subplots(2, 1, figsize=(18, 10), sharex=True, facecolor='#050505')

# Split channels
if len(y.shape) == 1:
    y_left = y
    y_right = y
else:
    y_left = y[0]
    y_right = y[1]

# Plot left channel
axes[0].plot(time_axis, y_left, color='#81C0C5', linewidth=0.5)
axes[0].set_title("L ON", loc='left', color='#888888', fontsize=11)
axes[0].grid(True, which='both', linestyle='-', linewidth=0.5)
axes[0].set_ylim(-1.1, 1.1)

# Plot right channel
axes[1].plot(time_axis, y_right, color='#81C0C5', linewidth=0.5)
axes[1].set_title("R ON", loc='left', color='#888888', fontsize=11)
axes[1].grid(True, which='both', linestyle='-', linewidth=0.5)
axes[1].set_ylim(-1.1, 1.1)

# Draw red lines for cuts
for cut in cut_details:
    t = cut["time"]
    event_type = cut["type"]
    
    # Skip start point at 0s
    if t == 0.0:
        continue
        
    # Draw vertical red lines across both channels
    axes[0].axvline(x=t, color='#FF3B30', linestyle='-', linewidth=1.5, alpha=0.95)
    axes[1].axvline(x=t, color='#FF3B30', linestyle='-', linewidth=1.5, alpha=0.95)
    
    # Label the cut type and timestamp
    axes[0].text(t, 1.05, f"{event_type.upper()}\n{t:.2f}s", color='#FF453A', fontsize=8, 
                 horizontalalignment='center', verticalalignment='bottom', fontweight='bold',
                 bbox=dict(facecolor='#050505', edgecolor='none', pad=2))

axes[1].set_xlabel("Time (seconds)", color='#ffffff', fontsize=13)
plt.xlim(0, duration)
plt.tight_layout()

# Save final render to brain directory
os.makedirs(os.path.dirname(output_path), exist_ok=True)
plt.savefig(output_path, dpi=200, bbox_inches='tight', facecolor=fig.get_facecolor(), edgecolor='none')
print(f"Chart successfully saved to: {output_path}")
