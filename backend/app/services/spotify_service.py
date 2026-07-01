from __future__ import annotations
"""
spotify_service.py
------------------
Finds the hookline (chorus) start timestamp for a given song using the
Spotify Audio Analysis API.

Fallback: returns 0.0 in ALL error scenarios so the music pipeline is
never blocked by a missing Spotify credential or an unavailable song.
"""

import os
import logging

logger = logging.getLogger(__name__)


def get_spotify_hookline_start(song_title: str, artist: str | None = None) -> float:
    """
    Query the Spotify Audio Analysis API to find the start timestamp (in seconds)
    of the hookline (the loudest / most energetic section) for the given song.

    Returns 0.0 as a safe fallback in all error / not-found scenarios.

    Args:
        song_title: The name of the song (e.g. "Kesariya").
        artist:     Optional artist name to narrow search (e.g. "Arijit Singh").

    Returns:
        float -- start time in seconds of the hookline, or 0.0 if undetectable.
    """
    client_id = os.getenv("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.getenv("SPOTIFY_CLIENT_SECRET", "").strip()

    # Guard: credentials not configured yet
    if not client_id or not client_secret or client_id.startswith("your_"):
        logger.warning(
            "[Spotify] SPOTIFY_CLIENT_ID / SPOTIFY_CLIENT_SECRET not set. "
            "Skipping hookline detection, using audio from 0:00."
        )
        return 0.0

    try:
        import spotipy
        from spotipy.oauth2 import SpotifyClientCredentials
    except ImportError:
        logger.warning(
            "[Spotify] 'spotipy' not installed. "
            "Run: pip install spotipy>=2.23.0  |  Falling back to 0:00."
        )
        return 0.0

    try:
        # Authenticate (Client Credentials - no user login needed)
        auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
        sp = spotipy.Spotify(auth_manager=auth_manager)

        # Search for the track on Spotify
        query = f"{song_title} {artist}" if artist else song_title
        results = sp.search(q=query, type="track", limit=1)
        tracks = results.get("tracks", {}).get("items", [])

        if not tracks:
            logger.info(
                f"[Spotify] No track found for query '{query}'. "
                "Falling back to 0:00."
            )
            return 0.0

        track_id = tracks[0]["id"]
        matched_name = tracks[0]["name"]
        matched_artist = tracks[0]["artists"][0]["name"] if tracks[0]["artists"] else "Unknown"
        logger.info(
            f"[Spotify] Matched '{query}' -> '{matched_name}' by {matched_artist} "
            f"(track_id={track_id})"
        )

        # Fetch audio analysis
        analysis = sp.audio_analysis(track_id)
        sections = analysis.get("sections", [])

        if not sections:
            logger.info(
                f"[Spotify] Audio analysis returned no sections for '{matched_name}'. "
                "Falling back to 0:00."
            )
            return 0.0

        # Find the loudest section (hookline / chorus)
        # Spotify reports loudness as negative dB - the least negative = loudest.
        hookline_section = max(sections, key=lambda s: s.get("loudness", -60.0))
        hook_start = float(hookline_section.get("start", 0.0))
        hook_loudness = hookline_section.get("loudness", 0.0)

        logger.info(
            f"[Spotify] Hookline detected at {hook_start:.1f}s "
            f"(loudness={hook_loudness:.1f} dB) for '{matched_name}'."
        )
        return hook_start

    except Exception as e:
        logger.warning(
            f"[Spotify] Hookline detection failed for '{song_title}': {e}. "
            "Falling back to 0:00."
        )
        return 0.0
