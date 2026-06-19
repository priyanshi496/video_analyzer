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

def resolve_song_by_key(minio_key: str, query: str, tmpdir: str) -> str:
    """
    Checks MinIO cache for key. If it exists, downloads it to tmpdir.
    If not, downloads using yt-dlp, uploads to MinIO at that key, and returns the path.
    """
    local_filename = os.path.basename(minio_key)
    local_path = os.path.join(tmpdir, local_filename)
    
    # Check MinIO
    if storage_service.object_exists(minio_key):
        logger.info(f"Cache hit in MinIO for {minio_key}. Downloading...")
        try:
            storage_service.download_file(minio_key, local_path)
            return local_path
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
        return local_path
        
    return ""

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

def resolve_custom_music(custom_query: str, tmpdir: str) -> str:
    """
    Resolves custom song query. If the query matches (or partially matches)
    a song track/keyword/slug in the preseeded catalog, it directly returns
    the catalog song from MinIO without initiating a new download.
    Otherwise, it uses the LLM to expand the query, checks if cached in
    MinIO under custom prefix, and downloads only if missing.
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
        return resolve_song_by_key(minio_key, catalog_match["query"], tmpdir)

    # Cache miss on pre-seeded catalog -> Expand query using LLM and check custom cache
    logger.info(f"Custom query '{custom_query}' not found in pre-seeded catalog. Expanding via LLM...")
    expanded = expand_short_query(custom_query)
    logger.info(f"Expanded custom query: '{expanded}'")
    
    slug = get_song_slug(expanded)
    minio_key = f"music/custom/{slug}.mp3"
    return resolve_song_by_key(minio_key, expanded, tmpdir)

def pick_ai_music(vibe: str, final_segs: list, tmpdir: str) -> str:
    """
    Pick the best song from the catalog based on the vibe preset and the vision analysis
    metadata (mood/vibe descriptions) in the final segments.
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
    
    # Analyze text for energy indicators
    energy_up = ["fast", "active", "energetic", "run", "jump", "dance", "happy", "party", "celebrate", "excited", "upbeat"]
    energy_down = ["slow", "calm", "peaceful", "quiet", "serene", "sad", "emotional", "relax", "meditative", "sleep"]
    
    energy_adj = 0
    for word in energy_up:
        energy_adj += full_text.count(word)
    for word in energy_down:
        energy_adj -= full_text.count(word)
        
    scaled_adj = max(-2, min(2, energy_adj // 3)) if energy_adj != 0 else 0
    target_energy = max(1, min(10, vibe_target_energy + scaled_adj))
    
    logger.info(f"AI Music Selection: vibe={vibe}, vibe_target_energy={vibe_target_energy}, text_adj={scaled_adj}, final_target_energy={target_energy}")
    
    best_song = None
    best_score = -9999
    
    for song in catalog:
        score = 0
        
        # Primary vibe matching
        if vibe.lower() in [vt.lower() for vt in song.get("vibe_tags", [])]:
            score += 15
            
        # Energy closeness
        energy_diff = abs(song.get("energy", 5) - target_energy)
        score += (10 - energy_diff)
        
        # Mood word alignment
        song_mood = song.get("mood", "").lower()
        if song_mood == "romantic" and any(w in full_text for w in ["love", "couple", "romantic", "romance", "together"]):
            score += 5
        elif song_mood == "happy" and any(w in full_text for w in ["happy", "joy", "smile", "laugh", "cheerful"]):
            score += 5
        elif song_mood == "sad" and any(w in full_text for w in ["sad", "emotional", "cry", "poignant", "sorrow"]):
            score += 5
        elif song_mood == "devotional" and any(w in full_text for w in ["god", "temple", "prayer", "spiritual", "devotional", "holy"]):
            score += 5
        elif song_mood == "motivational" and any(w in full_text for w in ["motivational", "power", "win", "run", "workout"]):
            score += 5
        elif song_mood == "chill" and any(w in full_text for w in ["chill", "relax", "calm", "slow", "peaceful"]):
            score += 5
            
        if score > best_score:
            best_score = score
            best_song = song
            
    if best_song:
        logger.info(f"AI picked song: {best_song['track']} by {best_song['artist']} with score {best_score} (slug: {best_song['slug']})")
        slug = best_song["slug"]
        minio_key = f"music/catalog/{slug}.mp3"
        return resolve_song_by_key(minio_key, best_song["query"], tmpdir)
    
    return ""

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

def mix_music_into_video(video_path: str, music_path: str, output_path: str):
    """
    Replaces the video's audio entirely with the music track.
    Loops the music track infinitely to fill the video duration,
    applies a fade-out filter to the last 1 second of the audio, and
    saves the output to output_path.
    """
    duration = get_video_duration(video_path)
    start_fade = max(0.0, duration - 1.0)
    fade_duration = min(1.0, duration)
    
    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
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
