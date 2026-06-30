"""
Zoom Effects Service

Calculates zoom keyframes from detected important moments.
The actual FFmpeg filter string is built in podcast_service._build_zoom_filter,
which owns the eased zoompan expression. This service owns only:
  - calculate_zoom_keyframes   (moment → hold keyframe)
  - _calculate_moment_intensity (intensity heuristic)
  - validate_zoom_keyframes    (sanity-check before rendering)
  - generate_zoom_preview_data (frontend timeline markers)
"""

import logging
from typing import List, Dict, Any

logger = logging.getLogger(__name__)


class ZoomEffectsService:

    def __init__(self):
        self.default_zoom_intensity = 1.25  # Match with MAX_ZOOM constraint

    async def calculate_zoom_keyframes(
        self,
        important_moments: List[Dict],
        zoom_intensity: float = None,
    ) -> List[Dict]:
        """
        One hold-type keyframe per moment — simple, no merging bugs.
        Intensity is scaled by _calculate_moment_intensity.
        """
        if zoom_intensity is None:
            zoom_intensity = self.default_zoom_intensity

        logger.info(f"Calculating zoom effects for {len(important_moments)} moments")

        keyframes = []
        for moment in important_moments:
            zoom_level = self._calculate_moment_intensity(moment, zoom_intensity)
            keyframes.append({
                "start_time": max(0.0, moment["start_time"]),
                "end_time":   moment["end_time"],
                "zoom_start": zoom_level,
                "zoom_end":   zoom_level,
                "transition_type": "hold",
                "reason": moment.get("reason", "unknown"),
            })

        logger.info(f"Generated {len(keyframes)} zoom keyframes")
        return keyframes

    def _calculate_moment_intensity(self, moment: Dict, base_intensity: float) -> float:
        """Scale zoom level based on moment metadata."""
        multiplier_map = {"high": 1.0, "medium": 0.85, "low": 0.7}
        multiplier = multiplier_map.get(moment.get("intensity", "medium"), 0.85)

        # Small boost for high-signal reason types
        if moment.get("reason") in ("statistics", "key_insight", "strong_opinion"):
            multiplier = min(1.0, multiplier + 0.1)

        zoom_amount = (base_intensity - 1.0) * multiplier
        return round(1.0 + zoom_amount, 3)

    def validate_zoom_keyframes(self, keyframes: List[Dict]) -> List[str]:
        """
        Sanity-check zoom keyframes before passing to FFmpeg.
        Returns a list of issue strings (empty = clean).
        Call this after calculate_zoom_keyframes and log any issues.
        """
        issues = []
        if not keyframes:
            return issues

        for i, kf in enumerate(keyframes):
            for field in ("start_time", "end_time", "zoom_start", "zoom_end"):
                if field not in kf:
                    issues.append(f"Keyframe {i}: missing '{field}'")

            if kf.get("end_time", 0) <= kf.get("start_time", 0):
                issues.append(f"Keyframe {i}: end_time must be > start_time")

            for zfield in ("zoom_start", "zoom_end"):
                z = kf.get(zfield, 1.0)
                if z < 0.5 or z > 3.0:
                    issues.append(f"Keyframe {i}: {zfield}={z} out of range (0.5–3.0)")

        # Check for overlapping windows
        sorted_kfs = sorted(keyframes, key=lambda k: k.get("start_time", 0))
        for i in range(len(sorted_kfs) - 1):
            a, b = sorted_kfs[i], sorted_kfs[i + 1]
            if b.get("start_time", 0) < a.get("end_time", 0):
                issues.append(f"Overlapping keyframes {i} and {i + 1}")

        return issues

    def generate_zoom_preview_data(self, zoom_keyframes: List[Dict]) -> Dict[str, Any]:
        """Produce timeline marker data for the frontend."""
        if not zoom_keyframes:
            return {"markers": [], "max_zoom": 1.0}

        markers = []
        max_zoom = 1.0
        for kf in zoom_keyframes:
            intensity = max(kf.get("zoom_start", 1.0), kf.get("zoom_end", 1.0))
            markers.append({
                "start":      kf["start_time"],
                "end":        kf["end_time"],
                "zoom_start": kf["zoom_start"],
                "zoom_end":   kf["zoom_end"],
                "type":       kf.get("transition_type", "hold"),
                "reason":     kf.get("reason", ""),
                "intensity":  intensity,
            })
            max_zoom = max(max_zoom, intensity)

        return {
            "markers":          markers,
            "max_zoom":         max_zoom,
            "total_keyframes":  len(zoom_keyframes),
        }
