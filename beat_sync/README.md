# 🎵 beat_sync — Librosa Beat-Syncing Module

A **self-contained module** that integrates beat-synced background music into the Video Analyzer pipeline.

Every cut in the final reel will land precisely on a musical beat — the gold standard for TikTok and Instagram Reels editing.

---

## 📁 Folder Structure

```
beat_sync/
├── config.py           ← 🎵 CHANGE YOUR MUSIC PATH HERE
├── audio_analyzer.py   ← Librosa: extracts BPM + beat timestamps
├── segment_snapper.py  ← Snaps clip durations to nearest beat
├── audio_mixer.py      ← FFmpeg: bakes BGM into the final video
├── __init__.py         ← Public API: apply_beat_sync()
├── requirements.txt    ← librosa, soundfile, numpy
├── music/              ← Drop your .mp3 / .wav here
│   └── .gitkeep
└── README.md           ← This file
```

---

## 🚀 Quick Start

### 1. Install dependencies
```bash
pip install -r beat_sync/requirements.txt
```

### 2. Add your music
Drop your background music file into `beat_sync/music/`:
```bash
cp /path/to/your/song.mp3 beat_sync/music/background.mp3
```

### 3. Set the music path
Open `beat_sync/config.py` and update the one line:
```python
BGM_PATH = "/path/to/video_analyzer/beat_sync/music/background.mp3"
```
Supported formats: `.mp3`, `.wav`, `.aac`, `.flac`, `.ogg`

### 4. Restart Celery
```bash
# Kill existing worker and restart
celery -A app.core.celery_app worker --loglevel=info --pool=solo
```

### 5. Run a new analysis job
The final video in MinIO will automatically have beat-synced music baked in. ✓

---

## ⚙️ Configuration (`config.py`)

| Setting | Default | Description |
|---|---|---|
| `BGM_PATH` | `beat_sync/music/background.mp3` | Path to your music file |
| `BGM_VOLUME` | `0.85` | Music volume (0.0–1.0) |
| `REPLACE_ORIGINAL_AUDIO` | `True` | `True` = music only, `False` = mix with original |
| `ORIGINAL_AUDIO_VOLUME` | `0.15` | Original audio volume when mixing |
| `SNAP_TOLERANCE_SEC` | `0.6` | Max seconds a clip can shift to snap to a beat |
| `MIN_CLIP_DURATION_SEC` | `0.5` | Clips are never shortened below this |
| `VERBOSE_LOGGING` | `False` | Log every snap decision |

---

## 🧠 How It Works

```
BGM file
    ↓
[audio_analyzer.py] → librosa.beat.beat_track()
    ↓
BeatMap(tempo_bpm=128.0, beat_times=[0.47s, 0.93s, 1.40s, ...])
    ↓
[segment_snapper.py] → for each AI segment, snap end_sec to nearest beat
    ↓
snapped_segments (end_sec values aligned to music rhythm)
    ↓
[audio_mixer.py] → FFmpeg mixes BGM into the stitched video
    ↓
final_video_beat_synced.mp4 (uploaded to MinIO)
```

---

## 🔒 Safe Fallback

If **anything** fails (missing file, librosa not installed, FFmpeg error, etc.), the module logs a warning and the pipeline continues with the **original video unchanged**. It never crashes the analysis job.

---

## 📦 Sharing This Module

To share independently (without the rest of the backend):
```bash
zip -r beat_sync.zip beat_sync/
```

The recipient needs:
- Python 3.9+
- `pip install -r beat_sync/requirements.txt`
- FFmpeg installed (`brew install ffmpeg` on Mac)

---

## 🧪 Testing Individual Components

```bash
# Test beat extraction only
cd /path/to/video_analyzer
python beat_sync/audio_analyzer.py beat_sync/music/background.mp3

# Test segment snapping
python beat_sync/segment_snapper.py

# Test audio mixing only
python beat_sync/audio_mixer.py input_video.mp4 beat_sync/music/background.mp3 output.mp4
```

---

## 🚫 Disabling Beat Sync

To disable without deleting the module, comment out the hook in `pipeline_service.py`:

```python
# Beat sync is temporarily disabled — uncomment to re-enable
# try:
#     from beat_sync import apply_beat_sync
#     ...
```

---

## 📝 `.gitignore` Additions

Add these lines to your root `.gitignore` to keep music files private:
```
beat_sync/music/*.mp3
beat_sync/music/*.wav
beat_sync/music/*.aac
beat_sync/music/*.flac
beat_sync/music/*.ogg
```
