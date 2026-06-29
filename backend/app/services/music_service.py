import os
import re
import json
import logging
import subprocess
import shutil
import tempfile
from pathlib import Path
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)

def get_song_slug(query: str) -> str:
    """Normalizes query/song name into a clean hyphenated slug."""
    q = query.lower()
    q = re.sub(r'[^a-z0-9\s-]', '', q)
    q = re.sub(r'[\s-]+', '-', q)
    return q.strip('-')

def download_youtube_song(query: str, output_path: str) -> bool:
    """
    Downloads the audio for a song query from YouTube using yt-dlp and extracts as MP3.
    Saves to output_path.
    """
    import sys
    ytdlp_bin = "yt-dlp"
    venv_bin = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    if os.path.exists(venv_bin):
        ytdlp_bin = venv_bin

    with tempfile.TemporaryDirectory() as td:
        temp_out = os.path.join(td, "dl.%(ext)s")
        cmd = [
            ytdlp_bin,
            "--extract-audio",
            "--audio-format", "mp3",
            "--audio-quality", "0",
            "--no-playlist",
            "-o", temp_out,
            f"ytsearch1:{query}"
        ]
        logger.info(f"Running yt-dlp command: {' '.join(cmd)}")
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if result.returncode != 0:
            logger.error(f"yt-dlp failed with return code {result.returncode}. Stderr: {result.stderr}")
            return False
        
        expected_file = os.path.join(td, "dl.mp3")
        if os.path.exists(expected_file):
            shutil.move(expected_file, output_path)
            return True
        else:
            # Scan for any mp3 in the temp dir as a fallback
            for f in os.listdir(td):
                if f.endswith(".mp3"):
                    shutil.move(os.path.join(td, f), output_path)
                    return True
            logger.error("No mp3 file found in temp directory after yt-dlp execution.")
            return False

def resolve_song_by_key(minio_key: str, query: str, tmpdir: str) -> tuple[str, str]:
    """
    Checks MinIO cache for key. If it exists, downloads it to tmpdir.
    If not, downloads using yt-dlp, uploads to MinIO at that key, and returns the path.
    Returns a (local_path, song_title) tuple where song_title is derived from the query.
    """
    local_filename = os.path.basename(minio_key)
    local_path = os.path.join(tmpdir, local_filename)
    # Use the query as the song title identifier for downstream Spotify lookup
    song_title = query
    
    # Check MinIO
    if storage_service.object_exists(minio_key):
        logger.info(f"Cache hit in MinIO for {minio_key}. Downloading...")
        try:
            storage_service.download_file(minio_key, local_path)
            return local_path, song_title
        except Exception as e:
            logger.error(f"Failed to download cached song {minio_key} from MinIO: {e}. Falling back to yt-dlp.")
            
    # Cache miss or download error -> download using yt-dlp
    logger.info(f"Cache miss or fallback for {minio_key}. Downloading via yt-dlp...")
    success = download_youtube_song(query, local_path)
    if success and os.path.exists(local_path):
        try:
            logger.info(f"Uploading {local_path} to MinIO at {minio_key}...")
            with open(local_path, "rb") as f:
                storage_service.upload_file_obj(f, minio_key, content_type="audio/mpeg")
        except Exception as e:
            logger.error(f"Failed to upload downloaded song to MinIO: {e}")
        return local_path, song_title
        
    return "", song_title

def expand_short_query(query: str) -> str:
    """
    Uses the LLM to expand a short song name (e.g. 'yarana')
    into the format '<track> by <artist> official audio'.
    """
    from app.services.llm_service import call_openrouter_text
    prompt = (
        f"Identify the track name and the primary artist of the song from this short query: \"{query}\".\n"
        f"Respond with ONLY the expanded query in the exact format: \"[Track Name] by [Artist Name] official audio\".\n"
        f"Do not include any extra explanation, markdown, quotes or punctuation. Just return the string.\n"
        f"Example: Input \"yarana\" -> \"Yaarana by Kishore Kumar official audio\""
    )
    try:
        res = call_openrouter_text(prompt, model="google/gemini-flash-1.5-8b")
        cleaned = res.strip().replace('"', '').replace("'", "")
        if "by" in cleaned and "official audio" in cleaned:
            return cleaned
        return f"{query} official audio"
    except Exception as e:
        logger.error(f"Failed to expand query via LLM: {e}")
        return f"{query} official audio"

def resolve_custom_music(custom_query: str, tmpdir: str, skip_llm_expand: bool = False) -> tuple[str, str]:
    """
    Resolves custom song query. Returns a (local_path, song_title) tuple.
    If the query matches (or partially matches) a song in the preseeded catalog,
    it directly returns the catalog song. Otherwise expands via LLM and downloads.
    """
    normalized = custom_query.strip().lower()
    catalog_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core", "music_catalog.json")
    
    catalog_match = None
    if os.path.exists(catalog_path):
        try:
            with open(catalog_path, "r") as f:
                catalog = json.load(f)
            
            for song in catalog:
                track = song.get("track", "").lower()
                artist = song.get("artist", "").lower()
                slug = song.get("slug", "").lower()
                keywords = [k.lower() for k in song.get("keywords", [])]
                
                # Check for direct matching
                if normalized == track or normalized == slug or normalized in keywords:
                    catalog_match = song
                    break
                    
                # Check for substring matches or multi-word contains
                if normalized in track or track in normalized:
                    catalog_match = song
                    break
        except Exception as e:
            logger.error(f"Error checking catalog during custom resolution: {e}")

    if catalog_match:
        logger.info(f"Custom query '{custom_query}' matched catalog song: {catalog_match['track']} by {catalog_match['artist']}. Using cached catalog version.")
        slug = catalog_match["slug"]
        minio_key = f"music/catalog/{slug}.mp3"
        song_title = f"{catalog_match['track']} {catalog_match['artist']}"
        local_path, _ = resolve_song_by_key(minio_key, catalog_match["query"], tmpdir)
        return local_path, song_title

    # Cache miss on pre-seeded catalog -> Expand query if not skipped, check custom cache
    logger.info(f"Custom query '{custom_query}' not found in pre-seeded catalog.")
    if skip_llm_expand:
        expanded = f"{custom_query} official audio"
    else:
        logger.info("Expanding via LLM...")
        expanded = expand_short_query(custom_query)
    logger.info(f"Expanded custom query: '{expanded}'")
    
    slug = get_song_slug(expanded)
    minio_key = f"music/custom/{slug}.mp3"
    local_path, song_title = resolve_song_by_key(minio_key, expanded, tmpdir)
    return local_path, song_title

def pick_ai_music(vibe: str, final_segs: list, tmpdir: str) -> tuple[str, str]:
    """
    Pick the best song from the catalog based on the vibe preset and the vision analysis
    metadata (mood/vibe descriptions) in the final segments.
    Returns a (local_path, song_title) tuple.
    """
    catalog_path = os.path.join(os.path.dirname(__file__), "..", "core", "music_catalog.json")
    try:
        with open(catalog_path, "r") as f:
            catalog = json.load(f)
    except Exception as e:
        logger.error(f"Failed to load music catalog: {e}")
        return ""
    
    # 1. Target energy based on vibe preset
    vibe_target_energy = {
        "energetic": 9,
        "romantic": 4,
        "spiritual": 4,
        "cinematic": 7,
        "nostalgic": 5,
        "adventurous": 8,
        "garba": 9
    }.get(vibe.lower(), 6)
    
    # 2. Collect mood/vibe descriptions from the segments to compute adjustment
    segment_text = []
    for seg in final_segs:
        segment_text.append(seg.get("mood", "").lower())
        segment_text.append(seg.get("overall_mood", "").lower())
        segment_text.append(seg.get("overall_vibe", "").lower())
        segment_text.append(seg.get("video_summary", "").lower())
        segment_text.append(seg.get("what_happens", "").lower())
    
    full_text = " ".join(segment_text)
    
    logger.info(f"AI Music Selection: vibe={vibe}, delegating directly to LLM evaluation...")
    from app.services.llm_service import call_openrouter_text
    
    # Build catalog summary for LLM
    catalog_summary = []
    for song in catalog:
        catalog_summary.append({
            "slug": song.get("slug"),
            "artist": song.get("artist"),
            "track": song.get("track"),
            "mood": song.get("mood"),
            "energy": song.get("energy"),
            "keywords": song.get("keywords", [])
        })
        
    prompt = (
        f"You are a music supervisor. Based on the following video descriptions and mood flow, "
        f"select the single best song from the provided catalog.\n\n"
        f"Vibe requested: {vibe}\n"
        f"Video Summary:\n{full_text}\n\n"
        f"Catalog options:\n{json.dumps(catalog_summary, indent=2)}\n\n"
        f"Rules:\n"
        f"1. Choose the song that is culturally and semantically most appropriate for the video summary.\n"
        f"2. Ensure the energy and mood of the song match the requested vibe and video context.\n"
        f"3. Return ONLY the string value of the 'slug'.\n"
        f"4. If absolutely NONE of the songs fit the context, return ONLY the word 'NOT_FOUND'.\n"
    )
    
    try:
        text_model = "openrouter/owl-alpha"
        fallbacks = ["openai/gpt-oss-120b:free"]
        res = call_openrouter_text(prompt, model=text_model, fallbacks=fallbacks)
        slug_res = res.strip().strip('"').strip("'")
        if slug_res == "NOT_FOUND":
            logger.info("LLM determined no songs match the context. Returning empty.")
            return "", ""
            
        matched_song = next((s for s in catalog if s.get("slug") == slug_res), None)
        if matched_song:
            logger.info(f"LLM picked song: {matched_song['track']} by {matched_song['artist']} (slug: {slug_res})")
            minio_key = f"music/catalog/{slug_res}.mp3"
            song_title = f"{matched_song['track']} {matched_song['artist']}"
            local_path, _ = resolve_song_by_key(minio_key, matched_song["query"], tmpdir)
            return local_path, song_title
        else:
            logger.warning(f"LLM returned unknown slug: {slug_res}. Returning empty.")
            return "", ""
    except Exception as e:
        logger.error(f"Failed LLM music selection: {e}")
        return "", ""

def get_video_duration(video_path: str) -> float:
    """Uses ffprobe to find the duration of a video file."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", video_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode == 0:
        try:
            return float(res.stdout.strip())
        except ValueError:
            pass
    return 30.0

def mix_music_into_video(video_path: str, music_path: str, output_path: str, audio_start: float = 0.0):
    """
    Replaces the video's audio entirely with the music track.
    Loops the music track infinitely to fill the video duration,
    applies a fade-out filter to the last 1 second of the audio, and
    saves the output to output_path.

    audio_start: seek position (seconds) in the music file to start from.
                 Use this to skip the intro and start at the hookline / chorus.
                 Defaults to 0.0 (beginning of the track).
    """
    duration = get_video_duration(video_path)
    start_fade = max(0.0, duration - 2.0)
    fade_duration = min(1.5, duration)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-ss", str(audio_start),   # seek to hookline before feeding the audio
        "-stream_loop", "-1",
        "-i", music_path,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-af", f"afade=t=out:st={start_fade}:d={fade_duration}",
        "-t", f"{duration}",
        output_path
    ]
    
    logger.info(f"Mixing music into video. Video: {video_path}, Music: {music_path}, Output: {output_path}")
    logger.info(f"FFmpeg mix command: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        logger.error(f"FFmpeg mixing failed. Return code: {result.returncode}. Stderr: {result.stderr}")
        raise RuntimeError(f"FFmpeg mixing failed: {result.stderr}")
    logger.info(f"Successfully mixed music into {output_path}")

def generate_suno_prompt_from_descriptions(vibe: str, final_segs: list, instrumental: bool) -> str:
    """
    Extracts mood, vibe, and visual summary descriptions from the segment metadata
    and queries the LLM to output a concise, highly-stylized, comma-separated music prompt 
    appropriate for Suno AI music generation.
    """
    from app.services.llm_service import call_openrouter_text
    
    descriptions = []
    for idx, seg in enumerate(final_segs):
        desc = f"Segment {idx + 1}: {seg.get('what_happens', '')}. Mood: {seg.get('mood', '') or seg.get('overall_mood', '')}."
        descriptions.append(desc)
    
    full_desc = "\n".join(descriptions)
    
    inst_str = "instrumental (no vocals or lyrics)" if instrumental else "with vocals/lyrics"
    
    prompt = (
        f"You are a music prompt designer for Suno AI. Based on the following visual descriptions and mood flow of a video, "
        f"create a music prompt for generating a background track.\n\n"
        f"Vibe Preset: {vibe}\n"
        f"Music style requested: {inst_str}\n\n"
        f"Video Highlight Descriptions:\n{full_desc}\n\n"
        f"Rules for the prompt:\n"
        f"1. Describe the genre, instrumentation, mood, pacing/tempo, and overall style.\n"
        f"2. Be concise and comma-separated (e.g. 'upbeat acoustic folk, warm acoustic guitar, happy whistling, positive vibe, midtempo, 120 bpm').\n"
        f"3. Must be under 150 characters total.\n"
        f"4. Do NOT include track names, artist names, quotes, markdown, or any surrounding text. Just output the prompt itself.\n"
        f"Suno prompt:"
    )
    
    try:
        res = call_openrouter_text(prompt, model="google/gemini-flash-1.5-8b")
        cleaned = res.strip().replace('"', '').replace("'", "")
        cleaned = cleaned[:200]
        logger.info(f"Generated Suno prompt: '{cleaned}'")
        return cleaned
    except Exception as e:
        logger.error(f"Failed to generate Suno prompt: {e}")
        if instrumental:
            return f"uplifting cinematic instrumental, {vibe} background music, rich production"
        else:
            return f"uplifting vocal song, {vibe} style music"

def generate_suno_music(prompt: str, output_path: str, instrumental: bool) -> bool:
    """
    Generates music via sunoapi.org REST API and saves the output file.
    Uses polling-only flow (no webhook callback required).
    """
    import requests
    import time
    from app.core.config import settings
    
    api_key = os.environ.get("SUNO_API_KEY") or settings.SUNO_API_KEY
    if not api_key:
        logger.error("No SUNO_API_KEY found in environment variables or settings.")
        return False
        
    base_url = "https://api.sunoapi.org/api/v1"
    
    # Restored callBackUrl placeholder to satisfy Suno API request validation constraints
    payload = {
        "model": "V4",
        "customMode": False,
        "instrumental": instrumental,
        "prompt": prompt[:500],
        "callBackUrl": "https://example.com/callback"
    }
    
    try:
        logger.info(f"Submitting Suno generation request with prompt: '{prompt}'")
        resp = requests.post(
            f"{base_url}/generate",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            },
            json=payload,
            timeout=30
        )
        resp.raise_for_status()
        data = resp.json()
        logger.info(f"Suno submit response: {data}")

        # Extract taskId from various possible nesting levels
        task_id = None
        if isinstance(data.get("data"), dict):
            task_id = data["data"].get("taskId") or data["data"].get("task_id")
        if not task_id:
            task_id = data.get("taskId") or data.get("task_id")
        
        if not task_id:
            logger.error(f"No taskId found in Suno response: {data}")
            return False
            
        logger.info(f"Suno task submitted. Task ID: {task_id}. Polling for completion...")
        
        # Poll for completion
        max_wait = 300
        poll_interval = 20
        elapsed = 0
        
        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval
            
            poll_resp = requests.get(
                f"{base_url}/generate/record-info",
                params={"taskId": task_id},
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=30
            )
            poll_resp.raise_for_status()
            result = poll_resp.json()
            logger.info(f"Suno poll [{elapsed}s]: {result}")

            # Navigate the response: try multiple nesting levels
            result_data = result.get("data") or {}
            if not isinstance(result_data, dict):
                result_data = {}

            status = result_data.get("status") or result.get("status", "")
            logger.info(f"Suno status: {status}")

            if status == "SUCCESS":
                # Extract tracks — try all common nesting patterns:
                # Pattern A: result["data"]["data"] = [track, ...]
                # Pattern B: result["data"]["tracks"] = [track, ...]
                # Pattern C: result["data"] = [track, ...]   (flat list)
                # Pattern D: result["tracks"] = [track, ...]
                tracks = None
                logger.info(f"Full Suno poll result for track extraction: {json.dumps(result, indent=2)}")
                candidates = [
                    result_data.get("response", {}).get("sunoData") if isinstance(result_data.get("response"), dict) else None,
                    result_data.get("sunoData"),
                    result_data.get("data"),
                    result_data.get("tracks"),
                    result_data.get("response"),
                    result.get("tracks"),
                    result.get("data") if isinstance(result.get("data"), list) else None,
                ]
                for candidate in candidates:
                    if isinstance(candidate, list) and len(candidate) > 0:
                        tracks = candidate
                        break
                
                if not tracks:
                    logger.error(f"Suno returned SUCCESS but could not find tracks in response: {result}")
                    return False
                    
                # Get audio URL from first track
                track = tracks[0]
                audio_url = None
                if isinstance(track, dict):
                    audio_url = (
                        track.get("audio_url")
                        or track.get("audioUrl")
                        or track.get("url")
                        or track.get("stream_audio_url")
                    )

                if not audio_url:
                    logger.error(f"No audio_url found in Suno track: {track}")
                    return False
                    
                logger.info(f"Suno generation complete. Downloading from {audio_url}...")
                dl_resp = requests.get(audio_url, timeout=120)
                dl_resp.raise_for_status()
                
                output_path_obj = Path(output_path)
                output_path_obj.parent.mkdir(parents=True, exist_ok=True)
                output_path_obj.write_bytes(dl_resp.content)
                logger.info(f"✓ Suno music saved to {output_path}")
                return True
                
            elif status in ("CREATE_TASK_FAILED", "GENERATE_AUDIO_FAILED", "SENSITIVE_WORD_ERROR", "FAILED"):
                logger.error(f"Suno generation failed with status: {status}. Full response: {result}")
                return False
            else:
                logger.info(f"Suno still generating ({elapsed}s elapsed)... status={status or 'pending'}")
                
        logger.error(f"Suno generation timed out after {max_wait} seconds.")
        return False
        
    except Exception as e:
        logger.error(f"Exception during Suno music generation: {e}")
        return False


def resolve_suno_music(vibe: str, final_segs: list, instrumental: bool, tmpdir: str) -> str:
    """
    Constructs a prompt based on segment descriptions, generates/downloads Suno music,
    caches the generated music in MinIO to avoid duplicate generation, and returns the local file path.
    """
    prompt = generate_suno_prompt_from_descriptions(vibe, final_segs, instrumental)
    slug = get_song_slug(prompt)
    if instrumental:
        slug = f"{slug}-instrumental"
    else:
        slug = f"{slug}-vocal"
    
    minio_key = f"music/suno/{slug}.mp3"
    local_path = os.path.join(tmpdir, f"{slug}.mp3")
    
    # Check MinIO cache
    try:
        if storage_service.object_exists(minio_key):
            logger.info(f"Cache hit in MinIO for generated Suno music: {minio_key}. Downloading...")
            storage_service.download_file(minio_key, local_path)
            return local_path
    except Exception as e:
        logger.error(f"Failed to download cached Suno music {minio_key} from MinIO: {e}")
            
    # Cache miss -> generate
    logger.info(f"Cache miss for {minio_key}. Triggering Suno AI generation...")
    success = generate_suno_music(prompt, local_path, instrumental)
    if success and os.path.exists(local_path):
        try:
            logger.info(f"Uploading generated Suno music to MinIO: {minio_key}...")
            with open(local_path, "rb") as f:
                storage_service.upload_file_obj(f, minio_key, content_type="audio/mpeg")
        except Exception as e:
            logger.error(f"Failed to upload Suno music to MinIO: {e}")
        return local_path
        
    return ""

