"""
config.py — Central configuration for the Video Timeline Analyzer.
"""

CONFIG = {
    # ── Vision Model Chain ────────────────────────────────────────────────────
    
    "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",

    # Fallbacks tried IN ORDER if primary fails or returns invalid JSON
    "fallback_models": [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free",
        "google/gemma-4-31b-it:free",  # free fallback
    ],

    # Max tokens limits for API calls to prevent reasoning model over-thinking
    "max_tokens_vision": 2048,
    "max_tokens_text":   1000,

    # ── Story Ordering Model ──────────────────────────────────────────────────
    # Text-only call — cheap, can use a fast model
    "story_order_model":    "openai/gpt-oss-120b:free",
    "story_order_fallback": "meta-llama/llama-3-8b-instruct:free",

    "max_parallel_vision_calls": 3,

    # Hard cap imposed by provider (Nemotron free: 8 images per request)
    "image_limit_per_request": 8,

    # Reference image budget — None = use remaining slots after frames
    "max_reference_images": None,

    # Adaptive frame counts by video length
    # Increased 'short' from 4→6 so continuous pans are detected correctly
    "adaptive_frames": {
        "short":  6,   # < 15s
        "medium": 6,   # 15–45s
        "long":   6,   # > 45s  (chunked, 6 frames per chunk)
    },

    # Chunking config — 45s window means 30s videos = 1 API call (was 15s = 3 calls)
    "chunk_window_sec":  45,
    "chunk_overlap_sec":  2,

    # ── API Rate Limiting & Retries ───────────────────────────────────────────
    "min_request_gap_sec": 2.0,   # 2s gap between calls (free models need more breathing room)
    "max_retries":         3,     # 3 attempts per chunk before quality-guided fallback kicks in
    "base_retry_sleep":    3.0,   # backoff: 3s, 6s, 12s — gives free models time to recover

    # Quality analysis — frame downscale width (360px = ~90% pixel reduction = 10-50x faster)
    "quality_downsample_width": 360,

    # Editor UI
    "editor_host": "127.0.0.1",
    "editor_port": 5050,

    # Output
    "reel_filename": "final_highlight_reel.mp4",
    "segments_json": "best_segments.json",
    "max_reel_sec": 60,

    # Black frame detection — mean brightness threshold (0–255)
    # If a clip's extracted frame mean brightness < this → show warning
    "black_frame_brightness_threshold": 20,
}
