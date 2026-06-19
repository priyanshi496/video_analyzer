"""
vibe_config.py — Vibe presets and their downstream rendering mappings.

The VIBE_MAP table is the single source of truth for how a user-selected vibe
translates into transitions and music genre when the rendering pipeline is built.

Each vibe entry contains:
  - transitions    : style of cut between clips
  - music_genre    : background music genre suggestion
  - ai_prompt_hint : short hint injected into the LLM story-order prompt
                     to nudge clip selection towards the desired vibe.

Note: clip_pace and color_grade will be added back when the rendering pipeline is built.
"""

from enum import Enum


class VibePreset(str, Enum):
    ENERGETIC   = "energetic"
    ROMANTIC    = "romantic"
    SPIRITUAL   = "spiritual"
    CINEMATIC   = "cinematic"
    NOSTALGIC   = "nostalgic"
    ADVENTUROUS = "adventurous"


# ── Vibe → Rendering Mapping Table ────────────────────────────────────────────
# This table will be consumed by the rendering/export pipeline in a future phase.
# Each vibe maps to:
#   - transitions    : style of cut between clips
#   - music_genre    : background music genre suggestion
#   - clip_pace      : preferred clip duration range in seconds
#   - color_grade    : visual color treatment preset
#   - ai_prompt_hint : short hint injected into the LLM story-order prompt
#                      to nudge clip selection towards the desired vibe.

VIBE_MAP: dict[str, dict] = {
    VibePreset.ENERGETIC: {
        "transitions":    "hard_cut",
        "music_genre":    "upbeat_edm_hiphop",
        "clip_pace":      "0.5-2.0",
        "ai_prompt_hint": (
            "Prioritize fast-paced, high-energy clips with motion, action, and excitement. "
            "Favor short, punchy segments. Avoid slow, static, or overly serene shots."
        ),
    },
    VibePreset.ROMANTIC: {
        "transitions":    "smooth_dissolve",
        "music_genre":    "acoustic_soft_piano",
        "clip_pace":      "2.0-4.0",
        "ai_prompt_hint": (
            "Prioritize intimate, warm, and soft moments. Favor golden-hour shots, "
            "close-ups of people, gentle interactions, and serene landscapes. "
            "Avoid chaotic or overly loud clips."
        ),
    },
    VibePreset.SPIRITUAL: {
        "transitions":    "slow_fade",
        "music_genre":    "ambient_devotional",
        "clip_pace":      "3.0-5.0",
        "ai_prompt_hint": (
            "Prioritize peaceful, contemplative, and serene clips. Favor wide shots of nature, "
            "quiet moments, spiritual or ceremonial scenes, and slow deliberate movement. "
            "Avoid abrupt or high-energy clips."
        ),
    },
    VibePreset.CINEMATIC: {
        "transitions":    "match_cut",
        "music_genre":    "orchestral_dramatic",
        "clip_pace":      "1.5-3.5",
        "ai_prompt_hint": (
            "Prioritize visually striking and narratively rich clips. Favor establishing shots, "
            "dramatic reveals, and clips with strong compositional framing. "
            "Build a clear story arc from setup to climax."
        ),
    },
    VibePreset.NOSTALGIC: {
        "transitions":    "film_grain_fade",
        "music_genre":    "lofi_retro",
        "clip_pace":      "1.5-3.0",
        "ai_prompt_hint": (
            "Prioritize clips that evoke warmth, memory, and sentimentality. Favor candid moments, "
            "group interactions, milestone events, and everyday beauty. "
            "Sequence clips to tell a personal journey story."
        ),
    },
    VibePreset.ADVENTUROUS: {
        "transitions":    "jump_cut_motion_blur",
        "music_genre":    "upbeat_rock_folk",
        "clip_pace":      "1.0-2.5",
        "ai_prompt_hint": (
            "Prioritize clips with movement, exploration, and discovery. Favor outdoor action shots, "
            "travel moments, physical activity, and wide scenic vistas. "
            "Build an arc from departure to arrival or challenge to triumph."
        ),
    },
}


def get_vibe_config(vibe: VibePreset) -> dict:
    """Returns the full rendering config for a given vibe preset."""
    return VIBE_MAP.get(vibe, VIBE_MAP[VibePreset.CINEMATIC])


def get_ai_prompt_hint(vibe: VibePreset) -> str:
    """Returns just the AI prompt hint for a given vibe, for injection into LLM prompts."""
    return VIBE_MAP.get(vibe, VIBE_MAP[VibePreset.CINEMATIC])["ai_prompt_hint"]
