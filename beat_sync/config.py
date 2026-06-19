"""
beat_sync/config.py
───────────────────────────────────────────────────────────────────────────────
🎵  BEAT SYNC CONFIGURATION — CHANGE YOUR MUSIC HERE
───────────────────────────────────────────────────────────────────────────────

This is the ONLY file you need to edit to change music or tune the behaviour.

Steps:
  1. Drop your .mp3 (or .wav, .aac, .flac, .ogg) file into beat_sync/music/
  2. Update BGM_PATH below to point to that file
  3. Restart the Celery worker
  4. Run a new analysis job — the final video will be beat-synced automatically
"""

import os
from pathlib import Path

# ── 🎵 Music File ─────────────────────────────────────────────────────────────
# Absolute path to your background music file.
# You can use any of: .mp3, .wav, .aac, .flac, .ogg
#
# Default: looks inside beat_sync/music/ folder next to this file.
# You can also use a full absolute path, e.g.:
#   BGM_PATH = "/Users/yourname/Music/my_track.mp3"

BGM_PATH = str(Path(__file__).parent / "music" / "Ilahi.mp3")

# ── 🔊 Volume & Audio Behaviour ───────────────────────────────────────────────
# BGM volume level:
#   0.0 = completely silent  |  1.0 = full volume  |  0.8 = 80% (recommended)
BGM_VOLUME = 0.85

# If True  → BGM completely REPLACES original clip audio (recommended for reels)
# If False → BGM is MIXED on top of original audio (original audio ducked down)
REPLACE_ORIGINAL_AUDIO = True

# Original audio volume when mixing (only used when REPLACE_ORIGINAL_AUDIO=False)
# Typically set low (0.1-0.2) so BGM dominates but ambient sound is audible
ORIGINAL_AUDIO_VOLUME = 0.15

# ── ⏱ Beat Snapping Behaviour ─────────────────────────────────────────────────
# Maximum distance (in seconds) an end_sec is allowed to move to snap to a beat.
# If the nearest beat is FURTHER away than this, the clip keeps its original end_sec.
# Increase for looser snapping, decrease for tighter (more conservative) snapping.
SNAP_TOLERANCE_SEC = 1.0

# Minimum clip duration after snapping (clips won't be shortened below this)
MIN_CLIP_DURATION_SEC = 0.5

# ── 🧪 Debug / Logging ────────────────────────────────────────────────────────
# Set to True to log the beat map and every snap decision to the console
VERBOSE_LOGGING = False
