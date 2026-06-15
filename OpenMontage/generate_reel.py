import json
import os
import sys
import time
import subprocess
import shutil
from pathlib import Path
import requests
from dotenv import load_dotenv

# Ensure the OpenMontage directory (current script's directory) is in sys.path so 'tools' imports work correctly
script_dir = Path(__file__).resolve().parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from tools.video.video_compose import VideoCompose
from tools.audio.audio_mixer import AudioMixer
from tools.audio.tts_selector import TTSSelector
from tools.audio.pixabay_music import PixabayMusic

# Load environment variables from parent workspace directory first
load_dotenv(dotenv_path=script_dir.parent / ".env")
load_dotenv()

# --- Configuration ---
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL_NAME = "openrouter/owl-alpha"

# Try collected_clips.json, fallback to active_segments.json in parent or current dir
workspace_root = script_dir.parent
if os.path.exists(workspace_root / "collected_clips.json"):
    CLIPS_JSON_PATH = workspace_root / "collected_clips.json"
elif os.path.exists("collected_clips.json"):
    CLIPS_JSON_PATH = Path("collected_clips.json")
elif os.path.exists(workspace_root / "active_segments.json"):
    CLIPS_JSON_PATH = workspace_root / "active_segments.json"
elif os.path.exists("active_segments.json"):
    CLIPS_JSON_PATH = Path("active_segments.json")
else:
    CLIPS_JSON_PATH = workspace_root / "collected_clips.json"

# Create a unique directory for this run to keep all outputs separate
RUN_ID = time.strftime("%Y%m%d_%H%M%S")
RUN_DIR = workspace_root / "projects/my-reel" / "runs" / f"run_{RUN_ID}"
ASSETS_DIR = workspace_root / "projects/my-reel/assets"
CLIPS_DIR = ASSETS_DIR / "clips"
TRIMMED_DIR = RUN_DIR / "trimmed"
AUDIO_DIR = RUN_DIR / "audio"
OUTPUT_FILE = RUN_DIR / "polished_cinematic_reel.mp4"

# Set up directories
TRIMMED_DIR.mkdir(parents=True, exist_ok=True)
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

def generate_voiceover(text: str, output_path: str):
    """Generate TTS using OpenMontage's built-in TTSSelector, falling back to macOS 'say'."""
    print(f"\n🎙️ Generating voiceover for: \"{text}\"...")
    
    tts = TTSSelector()
    from tools.base_tool import ToolStatus
    
    if tts.get_status() == ToolStatus.AVAILABLE:
        print("Using OpenMontage built-in TTSSelector...")
        res = tts.execute({
            "text": text,
            "output_path": output_path
        })
        if res.success:
            print(f"✅ Generated voiceover at {output_path} (via selector)")
            return
        else:
            print(f"⚠️ Built-in TTSSelector failed: {res.error}. Falling back to system 'say'...")
            
    # System 'say' fallback
    print("Using system 'say' fallback...")
    aiff_path = str(output_path).replace('.wav', '.aiff')
    try:
        subprocess.run(["say", "-o", aiff_path, text], check=True)
        subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", aiff_path, output_path], check=True)
        if os.path.exists(aiff_path):
            os.remove(aiff_path)
        print(f"✅ Generated voiceover at {output_path} (via system say)")
    except Exception as e:
        print(f"❌ Failed voiceover generation: {e}")
        sys.exit(1)

def get_audio_duration(file_path: str) -> float:
    """Get the duration of an audio file in seconds."""
    cmd = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration", "-of",
        "default=noprint_wrappers=1:nokey=1", file_path
    ]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True)
    return float(result.stdout.strip())

def normalize_audio_inplace(file_path: str):
    """Normalize the audio file at file_path in-place using ffmpeg loudnorm filter."""
    import subprocess
    from pathlib import Path
    p = Path(file_path)
    if not p.exists():
        return
    temp_path = p.with_suffix(".norm_temp.mp3")
    try:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(p),
            "-filter:a", "loudnorm=I=-14:TP=-1.5:LRA=11",
            str(temp_path)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0 and temp_path.exists():
            p.unlink()
            shutil.move(str(temp_path), str(p))
            print(f"🔊 In-place normalized background music ({p.name}) to standard -14 LUFS.")
        else:
            print(f"⚠️ Audio normalization failed: {res.stderr}")
    except Exception as e:
        print(f"⚠️ Exception during audio normalization: {e}")
    finally:
        if temp_path.exists():
            temp_path.unlink()

def resolve_bgm_query_with_ai(query: str) -> str:
    """Resolve ANY bgm query — mood description, song name, partial name, misspelling —
    into a precise YouTube search string using the LLM. No hardcoding needed."""
    if not OPENROUTER_API_KEY:
        return f"{query} official audio"
    try:
        import sys as _sys
        _sys.path.append(str(workspace_root))
        from llm import call_openrouter_text
        from config import CONFIG

        prompt = f"""You are an expert music supervisor for films and reels, with deep knowledge of Bollywood, Hindi film music, Punjabi pop, and international music.

Your task: Given ANY kind of input below, return a precise YouTube search string that finds the SINGLE best matching official song.

Input: "{query}"

The input may be:
- A mood/vibe description: "warm lifestyle home vlog chill" → pick the best matching real song
- A partial/short song name: "deva deva", "namo", "ik vaari" → expand to full song + artist + movie
- A misspelling: "deva dev", "namo namo kedarnath" → correct and expand
- Already a full song name: "Kesariya Brahmastra Arijit Singh" → just clean up and add 'official audio'
- Genre/artist request: "arijit singh sad" → pick his most iconic sad song

MOOD → SONG MATCHING GUIDE (use this for mood descriptions):
🏠 lifestyle / home / daily / interior / vlog / cozy → Apna Bana Le Bhediya Arijit Singh
✈️ travel / journey / wanderlust / explore / adventure → Ilahi Yeh Jawaani Hai Deewani Arijit Singh
🌿 chill / peaceful / nature / scenic / lofi / calm → Khaabon Ke Parindey Zindagi Na Milegi Dobara Amit Trivedi
💑 romantic / love / couple / wedding / intimate → Kesariya Brahmastra Arijit Singh
😢 sad / emotional / nostalgic / missing / breakup → Channa Mereya Ae Dil Hai Mushkil Arijit Singh
🎉 festive / street / cultural / colorful / mela → Nagada Sang Dhol Goliyon Ki Raasleela Ram-Leela
🎊 party / dance / hype / club / energy / fun → Tauba Tauba Karan Aujla
💪 motivational / sports / hustle / power / grind → Kar Har Maidaan Fateh Sanju Sukhwinder Singh
🔱 devotional / temple / mandir / shrine / prayer / shiva / aarti / ganga / idol / deity / worship / offering / priest / pilgrimage / kirtan / sacred / holy / diya / lamp / candle / bhajan / puja / ritual → Deva Deva Brahmastra Arijit Singh Pritam
🌅 cinematic / epic / dramatic / intense → Kal Ho Naa Ho Sonu Nigam

CRITICAL WARNING: If the input contains ANY of these devotional/temple keywords — temple, mandir, shrine, aarti, ganga, deity, idol, worship, priest, puja, diya, lamp, bhajan, kirtan, sacred, holy, pilgrimage — you MUST use the 🔱 devotional category. Do NOT choose romantic songs for temple/spiritual content even if the lighting is warm or the mood is calm.

OUTPUT FORMAT: <Song Name> <Artist> <Movie/Album> official audio
Return ONLY the YouTube search string — no explanation, no quotes, no markdown."""

        text_model = CONFIG.get("story_order_model", MODEL_NAME)
        fallbacks = [CONFIG.get("story_order_fallback", "openai/gpt-oss-120b:free")]
        result = call_openrouter_text(prompt, OPENROUTER_API_KEY, text_model, fallbacks=fallbacks)
        resolved = result.strip().strip('"').strip("'").strip()
        if resolved:
            print(f"🎵 AI resolved BGM query: '{query}' → '{resolved}'")
            return resolved
    except Exception as e:
        print(f"⚠️ AI BGM resolution failed: {e}")
    return f"{query} official audio"

PRESET_SONGS = [
    {"artist": "Abhilipsa Panda", "track": "Har Har Shambhu", "query": "Har Har Shambhu Abhilipsa Panda official audio", "keywords": ["har har shambhu", "shambhu", "abhilipsa"]},
    {"artist": "Mithoon", "track": "Bolo Har Har Har", "query": "Bolo Har Har Har Mithoon official audio", "keywords": ["bolo har har", "bolo har har har", "mithoon"]},
    {"artist": "Vishal Mishra", "track": "Jai Shri Ram", "query": "Jai Shri Ram Vishal Mishra official audio", "keywords": ["jai shri ram", "shri ram", "ram siya ram vishal"]},
    {"artist": "Arijit Singh", "track": "Deva Deva", "query": "Deva Deva Arijit Singh official audio", "keywords": ["deva deva", "deva", "arijit deva"]},
    {"artist": "Amit Trivedi", "track": "Namo Namo", "query": "Namo Namo Amit Trivedi official audio", "keywords": ["namo namo", "namo", "amit trivedi namo"]},
    {"artist": "Kailash Kher", "track": "Kaun Hai Woh", "query": "Kaun Hai Woh Kailash Kher official audio", "keywords": ["kaun hai woh", "kaun hai vo", "kailash kher kaun"]},
    {"artist": "Shankar Mahadevan", "track": "Shiv Tandav Stotram", "query": "Shiv Tandav Stotram Shankar Mahadevan official audio", "keywords": ["shiv tandav", "tandav", "tandav stotram"]},
    {"artist": "Sachet Tandon", "track": "Ram Siya Ram", "query": "Ram Siya Ram Sachet Tandon official audio", "keywords": ["ram siya ram", "siya ram"]},
    {"artist": "A.R. Rahman", "track": "Kun Faya Kun", "query": "Kun Faya Kun A.R. Rahman official audio", "keywords": ["kun faya kun", "kun faya", "rahman kun"]},
    {"artist": "Anup Jalota", "track": "Achyutam Keshavam", "query": "Achyutam Keshavam Anup Jalota official audio", "keywords": ["achyutam keshavam", "achyutam", "keshavam"]},
    {"artist": "Jubin Nautiyal", "track": "Mere Ghar Ram Aaye Hain", "query": "Mere Ghar Ram Aaye Hain Jubin Nautiyal official audio", "keywords": ["mere ghar ram", "ram aaye hain", "jubin ram"]},
    {"artist": "Kailash Kher", "track": "Teri Deewani", "query": "Teri Deewani Kailash Kher official audio", "keywords": ["teri deewani", "deewani"]},
    {"artist": "Ajay Gogavale", "track": "Gajanana", "query": "Gajanana Ajay Gogavale official audio", "keywords": ["gajanana", "gajanan"]},
    {"artist": "Arijit Singh", "track": "Ilahi", "query": "Ilahi Arijit Singh official audio", "keywords": ["ilahi", "ye jawani hai deewani"]},
    {"artist": "Arijit Singh", "track": "Safar", "query": "Safar Arijit Singh official audio", "keywords": ["safar", "safarnama"]},
    {"artist": "Udit Narayan", "track": "Yun Hi Chala Chal", "query": "Yun Hi Chala Chal Udit Narayan official audio", "keywords": ["yun hi chala chal", "chala chal"]},
    {"artist": "Mohit Chauhan", "track": "Phir Se Ud Chala", "query": "Phir Se Ud Chala Mohit Chauhan official audio", "keywords": ["phir se ud chala", "ud chala"]},
    {"artist": "Mohit Chauhan", "track": "Khaabon Ke Parindey", "query": "Khaabon Ke Parindey Mohit Chauhan official audio", "keywords": ["khaabon ke parindey", "khabon ke parindey", "parindey"]},
    {"artist": "Pritam", "track": "Subhanallah", "query": "Subhanallah Pritam official audio", "keywords": ["subhanallah"]},
    {"artist": "Jasleen Royal", "track": "Heeriye", "query": "Heeriye Jasleen Royal official audio", "keywords": ["heeriye", "heeriya"]},
    {"artist": "Arijit Singh", "track": "Kesariya", "query": "Kesariya Arijit Singh official audio", "keywords": ["kesariya", "kesariyan"]},
    {"artist": "Anirudh Ravichander", "track": "Kanimaa", "query": "Kanimaa Anirudh Ravichander official audio", "keywords": ["kanimaa"]},
    {"artist": "Vishal Dadlani", "track": "Sher Khul Gaye", "query": "Sher Khul Gaye Vishal Dadlani official audio", "keywords": ["sher khul gaye", "sher khul"]},
    {"artist": "Karan Aujla", "track": "Tauba Tauba", "query": "Tauba Tauba Karan Aujla official audio", "keywords": ["tauba tauba", "tauba"]},
    {"artist": "Madhubanti Bagchi", "track": "Aaj Ki Raat", "query": "Aaj Ki Raat Madhubanti Bagchi official audio", "keywords": ["aaj ki raat"]},
    {"artist": "Arijit Singh", "track": "Jhoome Jo Pathaan", "query": "Jhoome Jo Pathaan Arijit Singh official audio", "keywords": ["jhoome jo pathaan", "jhoome jo pathan", "jhoome jo"]},
    {"artist": "Siddharth Mahadevan", "track": "Zinda", "query": "Zinda Siddharth Mahadevan official audio", "keywords": ["zinda bhag milkha", "zinda"]},
    {"artist": "Sukhwinder Singh", "track": "Kar Har Maidaan Fateh", "query": "Kar Har Maidaan Fateh Sukhwinder Singh official audio", "keywords": ["kar har maidaan", "maidaan fateh", "kar har maidan"]},
    {"artist": "Shankar Mahadevan", "track": "Lakshya", "query": "Lakshya Shankar Mahadevan official audio", "keywords": ["lakshya title track", "lakshya"]},
    {"artist": "Prateek Kuhad", "track": "Kasoor", "query": "Kasoor Prateek Kuhad official audio", "keywords": ["kasoor"]},
    {"artist": "Anuv Jain", "track": "Alag Aasmaan", "query": "Alag Aasmaan Anuv Jain official audio", "keywords": ["alag aasmaan", "alag aasman"]},
    {"artist": "Anuv Jain", "track": "Husn", "query": "Husn Anuv Jain official audio", "keywords": ["husn"]},
    {"artist": "Arijit Singh", "track": "O Maahi", "query": "O Maahi Arijit Singh official audio", "keywords": ["o maahi", "o mahi"]},
    {"artist": "Vishal Mishra", "track": "Sajni", "query": "Sajni Vishal Mishra official audio", "keywords": ["sajni", "sajni re"]},
    {"artist": "Arijit Singh", "track": "Apna Bana Le", "query": "Apna Bana Le Arijit Singh official audio", "keywords": ["apna bana le", "apna bana"]},
    {"artist": "Arijit Singh", "track": "What Jhumka", "query": "What Jhumka Arijit Singh official audio", "keywords": ["what jhumka", "jhumka"]}
]

def resolve_song_by_preset(user_query: str) -> str:
    if not user_query:
        return None
    user_query_clean = user_query.lower().strip()
    
    # Try exact or substring keyword matches first
    for preset in PRESET_SONGS:
        track_lower = preset["track"].lower()
        artist_lower = preset["artist"].lower()
        
        # Check exact matches
        if user_query_clean == track_lower or user_query_clean == f"{track_lower} {artist_lower}" or user_query_clean == f"{artist_lower} {track_lower}":
            return preset["query"]
        
        # Check keywords list
        for kw in preset.get("keywords", []):
            if kw in user_query_clean:
                return preset["query"]
                
    return None

def get_background_music(query: str, output_path: str, user_custom: bool = False):
    """Resolve the BGM query via AI, then scan local library / Pixabay / YouTube / Suno."""
    # Try resolving via presets first (so shorthand terms resolve instantly)
    preset_resolved = resolve_song_by_preset(query)
    if preset_resolved:
        print(f"🎯 Resolved BGM query '{query}' via presets to: '{preset_resolved}'")
        query = preset_resolved
        user_custom = True

    query_lower = query.lower()

    # Load YouTube Video ID cache
    yt_cache_path = workspace_root / "projects" / "my-reel" / "youtube_id_cache.json"
    yt_cache = {}
    if yt_cache_path.exists():
        try:
            yt_cache = json.loads(yt_cache_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # If the user manually typed a song name, skip AI resolution — search YouTube directly.
    # This prevents "Ganga Ke Kinare" → "Ganga Ke Kinare Lata Mangeshkar Ganga Ki Kasam official audio".
    if user_custom:
        if not query_lower.endswith("official audio"):
            query = f"{query} official audio"
            query_lower = query.lower()
        print(f"🔒 User-custom song — skipping AI resolution, searching directly: '{query}'")
    elif not query_lower.endswith("official audio"):
        query = resolve_bgm_query_with_ai(query)
        query_lower = query.lower()

    # A. First check the audio cache directory
    import re
    sanitized = re.sub(r'[^a-zA-Z0-9_\-]+', '_', query.lower()).strip('_')
    cache_dir = workspace_root / "projects" / "my-reel" / "audio_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / f"{sanitized}.mp3"
    
    if cache_file.exists():
        shutil.copy(str(cache_file), output_path)
        print(f"\n✅ Found and copied background music from local cache: {cache_file.name}")
        normalize_audio_inplace(output_path)
        # Update cache with normalized version
        try:
            shutil.copy(output_path, str(cache_file))
        except Exception:
            pass
        return

    def save_to_cache():
        if os.path.exists(output_path):
            try:
                shutil.copy(output_path, str(cache_file))
                print(f"💾 Cached background music to {cache_file}")
            except Exception as ce:
                print(f"⚠️ Failed to cache background music: {ce}")

    # Detect if this is a lyrical/specific song (AI resolved to "... official audio")
    # Lyrical songs must come from YouTube — Pixabay only has royalty-free instrumentals.
    is_lyrical = query_lower.endswith("official audio")

    # 1. First check the local music_library directory
    music_lib = workspace_root / "music_library"
    if music_lib.exists():
        tracks = list(music_lib.glob("*.mp3")) + list(music_lib.glob("*.wav"))
        if tracks:
            shutil.copy(str(tracks[0]), output_path)
            print(f"\n✅ Found and copied background music from library: {tracks[0].name}")
            normalize_audio_inplace(output_path)
            save_to_cache()
            return

    # 2. For lyrical songs → go straight to YouTube, skip Pixabay & Suno
    if is_lyrical:
        print(f"\n🎵 Lyrical song detected — downloading directly from YouTube: '{query}'...")
        try:
            import yt_dlp
            out_file = Path(output_path)
            if out_file.exists():
                out_file.unlink()

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(out_file.with_suffix('')),
                'noplaylist': True,
                'default_search': 'ytsearch',
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }

            cached_id = yt_cache.get(query.lower())
            success = False

            if cached_id:
                try:
                    print(f"🔗 Using cached YouTube Video ID: {cached_id} for query: '{query}'")
                    url = f"https://www.youtube.com/watch?v={cached_id}"
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        result = ydl.extract_info(url, download=True)
                        entry = result
                        if 'entries' in result and len(result['entries']) > 0:
                            entry = result['entries'][0]
                        if out_file.exists():
                            print(f"✅ Downloaded BGM from YouTube (via cached ID): {entry.get('title')} by {entry.get('uploader')}")
                            success = True
                except Exception as ce:
                    print(f"⚠️ Cached YouTube ID {cached_id} failed: {ce}. Falling back to live search...")
                    if out_file.exists():
                        out_file.unlink()

            if not success:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(f"ytsearch1:{query}", download=True)
                    entry = result
                    if 'entries' in result and len(result['entries']) > 0:
                        entry = result['entries'][0]
                    if out_file.exists():
                        video_id = entry.get('id')
                        print(f"✅ Downloaded BGM from YouTube: {entry.get('title')} by {entry.get('uploader')}")
                        if video_id:
                            yt_cache[query.lower()] = video_id
                            try:
                                yt_cache_path.write_text(json.dumps(yt_cache, indent=2), encoding="utf-8")
                                print(f"💾 Cached YouTube Video ID: '{video_id}' for query: '{query}'")
                            except Exception:
                                pass
                        success = True

            if success:
                normalize_audio_inplace(output_path)
                save_to_cache()
                return
        except Exception as e:
            print(f"⚠️ YouTube download failed: {e}")
        # Last resort for lyrical: sine tone (Pixabay/Suno won't have this song anyway)
        print("❌ Could not download the requested song from YouTube. Generating fallback tone...")
    else:
        # 3. For generic/instrumental queries → Pixabay first, then YouTube, then Suno
        print(f"\n🎵 Searching Pixabay Music for query: '{query}'...")
        from tools.audio.pixabay_music import PixabayMusic
        music_tool = PixabayMusic()
        res = music_tool.execute({
            "query": query,
            "output_path": output_path,
            "min_duration": 15,
            "max_duration": 120
        })
        if res.success:
            print(f"✅ Downloaded BGM from Pixabay: {res.data.get('track_title')} by {res.data.get('artist')}")
            normalize_audio_inplace(output_path)
            save_to_cache()
            return

        print(f"⚠️ Pixabay download failed: {res.error}")

        # 4. YouTube fallback for generic queries
        print(f"\n🎵 Falling back to YouTube search for: '{query}'...")
        try:
            import yt_dlp
            out_file = Path(output_path)
            if out_file.exists():
                out_file.unlink()

            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': str(out_file.with_suffix('')),
                'noplaylist': True,
                'default_search': 'ytsearch',
                'quiet': True,
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }],
            }

            cached_id = yt_cache.get(query.lower())
            success = False

            if cached_id:
                try:
                    print(f"🔗 Using cached YouTube Video ID: {cached_id} for query: '{query}'")
                    url = f"https://www.youtube.com/watch?v={cached_id}"
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        result = ydl.extract_info(url, download=True)
                        entry = result
                        if 'entries' in result and len(result['entries']) > 0:
                            entry = result['entries'][0]
                        if out_file.exists():
                            print(f"✅ Downloaded BGM from YouTube (via cached ID): {entry.get('title')} by {entry.get('uploader')}")
                            success = True
                except Exception as ce:
                    print(f"⚠️ Cached YouTube ID {cached_id} failed: {ce}. Falling back to live search...")
                    if out_file.exists():
                        out_file.unlink()

            if not success:
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    result = ydl.extract_info(f"ytsearch1:{query} audio", download=True)
                    entry = result
                    if 'entries' in result and len(result['entries']) > 0:
                        entry = result['entries'][0]
                    if out_file.exists():
                        video_id = entry.get('id')
                        print(f"✅ Downloaded BGM from YouTube: {entry.get('title')} by {entry.get('uploader')}")
                        if video_id:
                            yt_cache[query.lower()] = video_id
                            try:
                                yt_cache_path.write_text(json.dumps(yt_cache, indent=2), encoding="utf-8")
                                print(f"💾 Cached YouTube Video ID: '{video_id}' for query: '{query}'")
                            except Exception:
                                pass
                        success = True

            if success:
                normalize_audio_inplace(output_path)
                save_to_cache()
                return
        except Exception as e:
            print(f"⚠️ YouTube download failed: {e}")

        # 5. Suno AI generation (only for generic/instrumental, not lyrical)
        print(f"🎵 Falling back to Suno AI for BGM generation using prompt: '{query}'...")
        from tools.audio.suno_music import SunoMusic
        suno_tool = SunoMusic()
        if suno_tool.get_status() == suno_tool.get_status().UNAVAILABLE:
            print("❌ Error: Suno API key is not configured or Suno is unavailable.")
        else:
            res = suno_tool.execute({
                "prompt": query,
                "output_path": output_path,
                "instrumental": True
            })
            if res.success:
                print(f"✅ Generated BGM using Suno AI: {res.data.get('output')}")
                normalize_audio_inplace(output_path)
                save_to_cache()
                return
            else:
                print(f"⚠️ Suno AI generation failed: {res.error}")
    # 5. Fallback to public royalty-free MP3 download (sounds much better than a beep!)
    fallback_url = "https://www.chosic.com/wp-content/uploads/2021/07/Rain-and-Tears-chosic.com_.mp3"
    print(f"🎵 Downloading high-quality fallback travel music track from: {fallback_url}...")
    try:
        response = requests.get(fallback_url, timeout=30)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"✅ Successfully downloaded high-quality fallback track!")
        normalize_audio_inplace(output_path)
        save_to_cache()
        return
    except Exception as e:
        print(f"⚠️ Failed to download fallback MP3: {e}")
    # 5. Last resort fallback (sine tone)
    print("Generating fallback tone...")
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "sine=frequency=300:duration=30",
        "-af", "volume=0.2",
        output_path
    ]
    subprocess.run(cmd, check=True)
    print(f"✅ Generated BGM (sine fallback) at {output_path}")

def generate_srt_file(text: str, duration: float, start_offset: float, output_path: str):
    """Generate a clean, timed SRT subtitle file for a voiceover script."""
    import re
    # Split text into short phrases at punctuation boundaries
    phrases = [p.strip() for p in re.split(r'(?<=[,.;:!?])\s+|(?<=—)\s+', text.strip()) if p.strip()]
    if not phrases:
        phrases = [text.strip()]
        
    total_chars = sum(len(p) for p in phrases)
    if total_chars == 0:
        return
        
    srt_content = ""
    current_time = start_offset
    
    for idx, phrase in enumerate(phrases):
        # Apportion duration based on phrase character length fraction
        phrase_dur = (len(phrase) / total_chars) * duration
        end_time = current_time + phrase_dur
        
        def format_ts(seconds):
            h = int(seconds // 3600)
            m = int((seconds % 3600) // 60)
            s = int(seconds % 60)
            ms = int((seconds % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
            
        srt_content += f"{idx + 1}\n"
        srt_content += f"{format_ts(current_time)} --> {format_ts(end_time)}\n"
        srt_content += f"{phrase}\n\n"
        current_time = end_time
        
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(srt_content)
    print(f"✅ Generated SRT subtitles at {output_path}")

def get_ai_decisions(clips_metadata: list) -> dict:
    if not OPENROUTER_API_KEY:
        print("❌ Error: OPENROUTER_API_KEY not found in .env")
        sys.exit(1)
        
    print("\n🧠 Consulting AI Director (OpenRouter) for Script, BGM Query, and Transition Decisions...")
    
    clean_metadata = []
    for i, clip in enumerate(clips_metadata):
        clean_metadata.append({
            "clip_id": f"clip_{i:02d}",
            "description": clip.get("video_summary", clip.get("what_happens", "")),
            "mood": clip.get("overall_mood", ""),
            "vibe": clip.get("overall_vibe", ""),
            "location": clip.get("location_tag", ""),
            "story_role": clip.get("story_role", ""),
        })
    directives_path = workspace_root / "directives.txt"
    user_directives = ""
    caption_style = "cinematic"
    if directives_path.exists():
        directives_text = directives_path.read_text()
        user_directives = f"\n\nUSER INSTRUCTIONS: {directives_text}\nCRITICAL: The user provided custom instructions. You MUST strictly follow them for the Voiceover script and the BGM Search Query!\n"
        # Extract caption style
        import re
        match = re.search(r'Caption style: (.*)', directives_text)
        if match:
            caption_style = match.group(1).strip()
        
    prompt = f"""
    You are an expert film director and music supervisor. I am providing you with metadata and visual descriptions for {len(clean_metadata)} sequential video clips in a highlight reel.{user_directives}

    TASK 1 — Voiceover Script:
    Write a short, engaging voiceover script (15-20 words max) that captures the overall story arc.

    TASK 2 — BGM Song Selection:
    Pick ONE specific real song that perfectly matches the overall mood and visual vibe of these clips.
    CRITICAL: You MUST strictly match the Mood/energy requested in the USER INSTRUCTIONS! If they ask for 'energetic', pick an upbeat/hype song. If they ask for 'chill', pick a slow song.
    Output the song as: "<Song Name> <Artist> <Movie/Album> official audio"
    
    CRITICAL MOOD RULES — Read carefully before picking a song:
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    🏠 LIFESTYLE / HOME / DAILY VLOG (interior shots, rooms, home tour, daily routine):
       → Apna Bana Le Bhediya Arijit Singh official audio
       → Raataan Lambiyan Shershaah Jubin Nautiyal Asees Kaur official audio

    ✈️ TRAVEL / JOURNEY / EXPLORATION (airports, roads, nature, new places, wanderlust):
       → Ilahi Yeh Jawaani Hai Deewani Arijit Singh official audio
       → Safar Jab Harry Met Sejal Arijit Singh official audio
       → Khaabon Ke Parindey Zindagi Na Milegi Dobara Amit Trivedi official audio

    🎉 STREET FESTIVAL / CULTURAL / VIBRANT / COLORFUL CROWD (street scenes, markets, melas):
       ⚠️ This is NOT devotional — it is festive/celebratory!
       → Nagada Sang Dhol Goliyon Ki Raasleela official audio
       → Balam Pichkari Yeh Jawaani Hai Deewani official audio

    💑 ROMANTIC / COUPLE / LOVE (intimate moments, couples, sunsets, date scenes):
       → Kesariya Brahmastra Arijit Singh official audio
       → Tum Hi Ho Aashiqui 2 Arijit Singh official audio

    🎊 PARTY / DANCE / HYPE / CLUB (dancing, energy, celebrations, DJ, crowd energy):
       → Tauba Tauba Karan Aujla official audio
       → Badan Pe Sitaare Pehne Hue official audio

    🏋️ MOTIVATIONAL / SPORTS / HUSTLE / GRIND (workouts, achievement, training, wins):
       → Kar Har Maidaan Fateh Sanju Sukhwinder Singh official audio
       → Sher Khul Gaye Fighter Hrithik Roshan official audio

    🌿 CHILL / PEACEFUL / NATURE / SCENIC (landscapes, sunsets, forests, calm moments):
       → Khaabon Ke Parindey Zindagi Na Milegi Dobara official audio
       → Ik Vaari Ae Raabta Arijit Singh official audio

    😢 EMOTIONAL / NOSTALGIC / SAD (memories, goodbyes, rain, melancholy):
       → Channa Mereya Ae Dil Hai Mushkil Arijit Singh official audio
       → Kabira Yeh Jawaani Hai Deewani Rekha Bhardwaj official audio

     🔱 DEVOTIONAL / MYTHOLOGICAL / RELIGIOUS (temples, mandir, ganga, aarti, prayers, shrine, idol, diya, priest, puja, bhajan, pilgrimage, kirtan, sacred, holy — ANY religious/spiritual content):
        → Deva Deva Brahmastra Arijit Singh Pritam official audio
        → Namo Namo Kedarnath Amit Trivedi official audio
        → Kaun Hai Woh Bahubali Kailash Kher official audio
        → Mohit Chauhan Kun Faya Kun Rockstar official audio
    ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    TASK 3 — Transitions:
    Decide cinematic transitions between clips. Use varied effects — do NOT use 'crossfade' for everything.
    Options: "cut", "crossfade", "fade", "wipeleft", "wiperight", "slideup", "circlecrop", "dissolve", "pixelize", "zoomin", "glitch"

    Here is the clip sequence:
    {json.dumps(clean_metadata, indent=2)}

    OUTPUT FORMAT — valid JSON ONLY:
    {{
      "voiceover_script": "The journey begins as we take flight...",
      "bgm_search_query": "Ilahi Yeh Jawaani Hai Deewani Arijit Singh official audio",
      "transitions": [
        {{ "from": "clip_00", "to": "clip_01", "type": "crossfade", "duration": 0.5 }}
      ]
    }}
    """
    import sys
    sys.path.append(str(workspace_root))
    from llm import call_openrouter_text
    from prompts import parse_json_response
    from config import CONFIG
    
    text_model = CONFIG.get("story_order_model", MODEL_NAME)
    fallbacks = [CONFIG.get("story_order_fallback", "openai/gpt-oss-120b:free")]
    
    raw = call_openrouter_text(prompt, OPENROUTER_API_KEY, text_model, fallbacks=fallbacks)
    parsed = parse_json_response(raw)
    
    if not isinstance(parsed, dict):
        # Fallback empty decisions
        return {"voiceover_script": "", "bgm_search_query": "cinematic epic", "transitions": []}
        
    return parsed

def main():
    print("🎬 Starting Cinematic AI Director Pipeline\n")
    print(f"Reading clips metadata from: {CLIPS_JSON_PATH}")
    
    if not os.path.exists(CLIPS_JSON_PATH):
        print(f"❌ Could not find {CLIPS_JSON_PATH}.")
        sys.exit(1)
        
    with open(CLIPS_JSON_PATH, "r") as f:
        raw_clips_data = json.load(f)
        
    # Filter to only include used clips
    clips_data = [c for c in raw_clips_data if c.get("is_used", True)]
        
    # Feature Toggles
    enable_vo = False
    enable_bgm = os.getenv("ENABLE_BGM", "true").lower() == "true"
    enable_sub = False

    # Load UI Polish Settings if available
    polish_settings_path = workspace_root / "polish_settings.json"
    polish_settings = None
    if polish_settings_path.exists():
        try:
            with open(polish_settings_path, "r") as f:
                polish_settings = json.load(f)
                print("✨ Loaded UI Polish Settings!")
        except Exception as e:
            print(f"⚠️ Failed to load polish_settings.json: {e}")

    # ── Read caption scope from polish settings ──
    caption_mode = "per-clip"
    single_caption_text = None
    caption_position = "bottom"
    
    caption_style = "cinematic"
    directives_path = workspace_root / "directives.txt"
    directives_text = ""
    if directives_path.exists():
        directives_text = directives_path.read_text()
        import re
        match = re.search(r'Caption style: (.*)', directives_text)
        if match:
            caption_style = match.group(1).strip()
            
    directives_lower = directives_text.lower() if directives_text else ""
    if "top of te reel" in directives_lower or "top of the reel" in directives_lower or "place at top-center" in directives_lower or "caption position: top" in directives_lower:
        caption_position = "top"
    
    if polish_settings:
        if "caption_position" in polish_settings:
            caption_position = polish_settings["caption_position"]
        if "caption_style" in polish_settings:
            caption_style = polish_settings["caption_style"]
        if polish_settings.get("caption_mode") == "single":
            caption_mode = "single"
            caption_position = polish_settings.get("caption_position", "top")
            if polish_settings.get("captions") and len(polish_settings["captions"]) > 0:
                single_caption_text = polish_settings["captions"][0]
            else:
                single_caption_text = ""
            
    print(f"📝 Caption mode: {'single top-center' if caption_mode == 'single' else 'per-clip AI'} | position: {caption_position}")

    # Generate or skip AI Decisions (OpenRouter)
    is_bgm_user_custom = False
    # Read polish_settings music genre FIRST — if it's set, we don't need AI to pick BGM at all
    polish_bgm_query = None
    if polish_settings and "music" in polish_settings and "genre" in polish_settings["music"]:
        selected_genre = polish_settings["music"]["genre"]
        if selected_genre and selected_genre != "none":
            polish_bgm_query = selected_genre.replace("_", " ")
            is_bgm_user_custom = bool(polish_settings["music"].get("is_user_custom"))

    if polish_settings and not enable_vo:
        print("⚡ Skipping AI Director LLM call since UI Polish Settings are loaded and VO is disabled.")
        vo_text = ""
        bgm_query = polish_bgm_query or "calm travel music"
        ai_transitions = []
    else:
        decisions = get_ai_decisions(clips_data)
        vo_text = decisions.get("voiceover_script", "A wonderful journey.")
        ai_transitions = decisions.get("transitions", [])
        # Use polish_settings genre if available — NEVER let AI BGM override the user/AI-selected genre
        if polish_bgm_query:
            bgm_query = polish_bgm_query
            print(f"🎵 Using polish_settings genre for BGM: '{bgm_query}' (overrides AI BGM pick)")
        else:
            bgm_query = decisions.get("bgm_search_query", "calm travel music")
                    
    print("\n📝 AI Director Script:")
    print(f"   \"{vo_text}\"")
    
    # Generate Audio Assets
    vo_path = str(AUDIO_DIR / "voiceover.wav")
    bgm_path = str(AUDIO_DIR / "bgm.mp3")
    srt_path = str(AUDIO_DIR / "voiceover.srt")
    vo_duration = 0.0
    
    if enable_vo:
        generate_voiceover(vo_text, vo_path)
        vo_duration = get_audio_duration(vo_path) if os.path.exists(vo_path) else 3.0
    
    if enable_bgm:
        get_background_music(bgm_query, bgm_path, user_custom=is_bgm_user_custom)
    
    if enable_sub and enable_vo:
        # Generate the SRT Subtitle file dynamically
        generate_srt_file(vo_text, vo_duration, 0.5, srt_path)

    # Calculate beat synchronization values if BGM is enabled
    beat_interval = 0.0
    if enable_bgm:
        BPM_MAP = {
            "ilahi": 130,
            "khaabon ke parindey": 110,
            "safar": 120,
            "kun faya kun": 80,
            "subhanallah": 95,
            "tauba tauba": 122,
            "kanimaa": 125,
            "sher khul gaye": 124,
            "jai jai shivshankar": 128,
            "shaky": 120,
            "ghis ghis ghis": 125,
            "bairan": 118,
            "sitaare": 115,
            "deva deva": 118,
            "namo namo": 110,
            "kaun hai woh": 105,
            "bolo har har har": 120,
            "gajanana": 115,
        }
        
        HOOK_MAP = {
            "ilahi": 60.0,
            "khaabon ke parindey": 45.0,
            "safar": 50.0,
            "kun faya kun": 120.0,
            "subhanallah": 40.0,
            "tauba tauba": 65.0,
            "kanimaa": 55.0,
            "sher khul gaye": 45.0,
            "jai jai shivshankar": 40.0,
            "shaky": 30.0,
            "ghis ghis ghis": 35.0,
            "bairan": 45.0,
            "sitaare": 40.0,
            "deva deva": 60.0,
            "namo namo": 70.0,
            "kaun hai woh": 50.0,
            "bolo har har har": 45.0,
            "gajanana": 40.0,
        }
        selected_bpm = 120  # Default standard 120 BPM if not matched
        bgm_hook_offset = 0.0
        q_lower = bgm_query.lower()
        for known_song, bpm in BPM_MAP.items():
            if known_song in q_lower:
                selected_bpm = bpm
                bgm_hook_offset = HOOK_MAP.get(known_song, 40.0)
                print(f"🎵 Matched known song: {known_song} -> {bpm} BPM (Hook offset: {bgm_hook_offset}s)")
                break
                
        if polish_settings and "music" in polish_settings and "offset" in polish_settings["music"]:
            try:
                custom_offset = float(polish_settings["music"]["offset"])
                if custom_offset > 0:
                    bgm_hook_offset = custom_offset
                    print(f"🎵 Using custom music offset from UI: {bgm_hook_offset}s")
            except Exception:
                pass

        beat_interval = 60.0 / selected_bpm
        print(f"🎵 Beat synchronization active. Selected BPM: {selected_bpm} (Beat interval: {beat_interval:.3f}s)")

    # Build edit_decisions.json
    print("\n🧵 Building Edit Decisions for VideoCompose (Using Procedural Transitions)...")
    
    cuts = []
    for i, clip in enumerate(clips_data):
        raw_path = clip.get("video_path")
        if not raw_path or not os.path.exists(raw_path):
            idx = clip.get("video_idx", i)
            raw_path = str(CLIPS_DIR / f"clip_{idx}.mp4")
            
            if not os.path.exists(raw_path):
                # Fallback path scan in raw_clips or raw assets
                raw_path = str(workspace_root / "raw_clips" / f"clip_{idx}.mp4")
                if not os.path.exists(raw_path):
                    raw_path = str(workspace_root / "input_videos" / f"clip_{idx}.mp4")
                    if not os.path.exists(raw_path):
                        print(f"⚠️ Warning: Could not find raw video {raw_path}. Skipping.")
                        continue
            
        # Extract dynamic transitions decided procedurally OR from UI polish_settings
        t_out = "cut"
        t_dur = 0.0
        current_clip_id = f"clip_{i:02d}"
        
        # UI overrides
        if "polish_settings" in locals() and i < len(polish_settings.get("transitions", [])):
            t_val = polish_settings["transitions"][i]
            if t_val and t_val != "cut":
                t_out = t_val
                t_dur = 0.5
        else:
            for trans in ai_transitions:
                if trans.get("from") == current_clip_id:
                    t_out = trans.get("type", "cut")
                    t_dur = float(trans.get("duration", 0.0))
                    break
                
        # Fade out the very last clip as a cinematic outro
        if i == len(clips_data) - 1:
            t_out = "fade"
            t_dur = 1.0
            
        # PROBE ACTUAL DURATION and video streams to determine dimensions and prevent out-of-bounds trims
        in_s = float(clip.get("start_sec", 0.0))
        out_s = float(clip.get("end_sec", 3.0))
        
        actual_dur = out_s
        width, height = None, None
        try:
            probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", raw_path]
            probe_out = subprocess.check_output(probe_cmd, text=True)
            import json as json_mod
            probe_data = json_mod.loads(probe_out)
            actual_dur = float(probe_data.get("format", {}).get("duration", out_s))
            
            # Extract video stream dimensions
            for stream in probe_data.get("streams", []):
                if stream.get("codec_type") == "video":
                    width = int(stream.get("width", 0))
                    height = int(stream.get("height", 0))
                    break
            
            if out_s > actual_dur:
                print(f"⚠️ Clip {raw_path} is shorter ({actual_dur:.1f}s) than requested end_sec ({out_s}s). Assuming pre-trimmed.")
                in_s = 0.0
                out_s = actual_dur
        except Exception as e:
            print(f"⚠️ Warning: ffprobe failed for {raw_path}: {e}")
            actual_dur = out_s
            
        # Align clip duration to the beats of the BGM to change clips according to the beats
        if enable_bgm and beat_interval > 0:
            req_dur = out_s - in_s
            # Round duration to nearest beat multiple (min 2 beats duration to keep it viewable)
            multiplier = max(2, round(req_dur / beat_interval))
            aligned_dur = multiplier * beat_interval
            
            # Check if this aligned duration fits within actual video
            if in_s + aligned_dur <= actual_dur:
                out_s = in_s + aligned_dur
            elif aligned_dur <= actual_dur:
                # Shift start time back to fit the aligned duration
                in_s = max(0.0, actual_dur - aligned_dur)
                out_s = in_s + aligned_dur
            else:
                # If the video is shorter than aligned_dur, just use actual duration rounded down to nearest beat
                max_mult = int(actual_dur / beat_interval)
                if max_mult >= 1:
                    in_s = 0.0
                    out_s = max_mult * beat_interval
                else:
                    in_s = 0.0
                    out_s = actual_dur
            print(f"   ⏱️ Beat-sync clip {i} duration: {out_s - in_s:.2f}s ({multiplier} beats)")
            
        # ── Pre-trim clip using FFmpeg ──
        trimmed_name = f"clip_{i}_trimmed.mp4"
        trimmed_path = TRIMMED_DIR / trimmed_name
        clip_duration = out_s - in_s
        
        if clip_duration > 0:
            # Determine downscaling filter if the source is 4K (width or height > 1920)
            scale_filter = None
            if width and height and (width > 1920 or height > 1920):
                if width >= height:
                    # Landscape 4K -> 1080p Landscape (1920 width, height automatic and divisible by 2)
                    scale_filter = "scale=1920:-2"
                    print(f"      📉 Downscaling landscape 4K ({width}x{height}) to 1080p ({scale_filter})")
                else:
                    # Portrait 4K -> 1080p Portrait (1080 width or height automatic and divisible by 2)
                    scale_filter = "scale=-2:1920"
                    print(f"      📉 Downscaling portrait 4K ({width}x{height}) to 1080p ({scale_filter})")

            print(f"   🎬 Pre-trimming clip {i} with FFmpeg: {in_s:.2f}s to {out_s:.2f}s ({clip_duration:.2f}s) -> {trimmed_name}")
            trim_cmd = [
                "ffmpeg", "-y",
                "-ss", f"{in_s:.4f}",
                "-to", f"{out_s:.4f}",
                "-i", raw_path,
            ]
            if scale_filter:
                trim_cmd.extend(["-vf", scale_filter])
            trim_cmd.extend([
                "-c:v", "libx264",
                "-c:a", "aac",
                "-pix_fmt", "yuv420p",
                "-crf", "18",
                "-preset", "superfast",
                str(trimmed_path)
            ])
            try:
                subprocess.run(trim_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                source_for_remotion = str(trimmed_path)
                in_s_for_remotion = 0.0
                out_s_for_remotion = clip_duration
            except subprocess.CalledProcessError as e:
                err_log = e.stderr.decode('utf-8', errors='ignore') if e.stderr else str(e)
                print(f"   ⚠️ Warning: Pre-trimming failed for {raw_path}. Falling back to original. Error: {err_log}")
                source_for_remotion = raw_path
                in_s_for_remotion = in_s
                out_s_for_remotion = out_s
        else:
            source_for_remotion = raw_path
            in_s_for_remotion = in_s
            out_s_for_remotion = out_s

        cut_obj = {
            "id": f"cut_{i}",
            "source": source_for_remotion,
            "in_seconds": in_s_for_remotion,
            "out_seconds": out_s_for_remotion,
            "transition_out": t_out,
            "transition_duration": t_dur
        }

        # ── Apply captions ──
        final_style = caption_style
        if "polish_settings" in locals() and polish_settings and "caption_style" in polish_settings:
            final_style = polish_settings["caption_style"]

        if final_style == "none":
            cut_obj["captionText"] = ""
        elif single_caption_text is not None:
            # Single caption mode: same text on every clip, placed at top-center
            if single_caption_text:   # only if text was actually provided
                cut_obj["captionText"] = single_caption_text
                cut_obj["captionPosition"] = caption_position
        elif "polish_settings" in locals() and polish_settings and i < len(polish_settings.get("captions", [])):
            if polish_settings["captions"][i]:
                cut_obj["captionText"] = polish_settings["captions"][i]
                cut_obj["captionPosition"] = caption_position  # respects directives
        cut_obj["captionStyle"] = final_style
                
        cuts.append(cut_obj)
        
    edit_decisions = {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "cuts": cuts
    }
    
    bgm_volume = 0.3
    if polish_settings and "music" in polish_settings and "volume" in polish_settings["music"]:
        try:
            bgm_volume = float(polish_settings["music"]["volume"]) / 100.0
            print(f"🔊 Using dynamic music volume from UI: {bgm_volume}")
        except Exception:
            pass

    audio_config = {}
    if enable_vo and os.path.exists(vo_path):
        audio_config["narration"] = {
            "segments": [
                { "asset_id": vo_path, "start_seconds": 0.5, "end_seconds": 0.5 + vo_duration }
            ]
        }
        
    if enable_bgm and os.path.exists(bgm_path):
        audio_config["music"] = {
            "asset_id": bgm_path,
            "volume": bgm_volume,
            "ducking": True
        }
        if bgm_hook_offset > 0:
            audio_config["music"]["trimBeforeSeconds"] = bgm_hook_offset
        
    if audio_config:
        edit_decisions["audio"] = audio_config
        
    if enable_sub and enable_vo and os.path.exists(srt_path):
        edit_decisions["subtitles"] = {
            "enabled": True,
            "source": srt_path,
            "style": {
                "font": "Arial",
                "font_size": 28,
                "primary_color": "&HFFFFFF",
                "outline_color": "&H000000",
                "outline_width": 2.0,
                "margin_v": 50,
                "alignment": 2
            }
        }
    
    # Save the manifest just so the user can inspect it
    manifest_path = RUN_DIR / "edit_decisions.json"
    with open(manifest_path, "w") as f:
        json.dump(edit_decisions, f, indent=2)
        
    print(f"✅ Saved edit_decisions to {manifest_path}")

    # Synchronize edit decisions to Remotion composer for live preview
    try:
        composer_my_reel = workspace_root / "OpenMontage" / "remotion-composer" / "src" / "my_reel.json"
        composer_my_reel.parent.mkdir(parents=True, exist_ok=True)
        with open(composer_my_reel, "w", encoding="utf-8") as f:
            json.dump(edit_decisions, f, indent=2)
        print(f"✅ Synced edit decisions to Remotion composer: {composer_my_reel}")
    except Exception as e:
        print(f"⚠️ Warning: Failed to sync edit decisions to Remotion: {e}")

    # Mix Audio with AudioMixer
    mixed_audio_path = None
    
    if enable_vo and os.path.exists(vo_path) and enable_bgm and os.path.exists(bgm_path):
        print("\n🎛️ Mixing generated audio with AudioMixer...")
        mixer = AudioMixer()
        mixed_audio_path = str(AUDIO_DIR / "final_mixed_audio.wav")
        mix_res = mixer.execute({
            "operation": "full_mix",
            "tracks": [
                {"path": vo_path, "role": "speech", "start_seconds": 0.5},
                {"path": bgm_path, "role": "music", "volume": bgm_volume, "trim_start_seconds": bgm_hook_offset}
            ],
            "ducking": {"enabled": True, "music_volume_during_speech": 0.1},
            "output_path": mixed_audio_path
        })
        
        if not mix_res.success:
            print(f"❌ Audio mixing failed: {mix_res.error}")
            sys.exit(1)
    elif enable_vo and os.path.exists(vo_path):
        mixed_audio_path = vo_path
    elif enable_bgm and os.path.exists(bgm_path):
        mixed_audio_path = bgm_path

    # Execute Composition (using Remotion to support visual transitions)
    print(f"\n🎬 Rendering final video with OpenMontage VideoCompose (Remotion)...")
    
    edit_decisions["render_runtime"] = "remotion"
    edit_decisions["renderer_family"] = "cinematic-trailer"
    
    composer = VideoCompose()
    
    compose_payload = {
        "operation": "remotion_render",
        "output_path": str(OUTPUT_FILE),
        "edit_decisions": edit_decisions
    }
    if mixed_audio_path:
        compose_payload["audio_path"] = mixed_audio_path
        
    result = composer.execute(compose_payload)
    
    if result.success:
        print(f"\n✅ Success! Cinematic reel saved to: {OUTPUT_FILE}")
        
        # Mux the SRT subtitles into the MP4 as a soft subtitle track to bypass the libass error
        if enable_sub and enable_vo and os.path.exists(srt_path):
            print("📝 Muxing soft subtitles into video...")
            muxed_output = OUTPUT_FILE.parent / "polished_cinematic_reel_with_subs.mp4"
            mux_cmd = [
                "ffmpeg", "-y",
                "-i", str(OUTPUT_FILE),
                "-i", srt_path,
                "-c", "copy",
                "-c:s", "mov_text",
                str(muxed_output)
            ]
            try:
                subprocess.run(mux_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                # Replace original with muxed version
                muxed_output.replace(OUTPUT_FILE)
                print("✅ Subtitles successfully added!")
            except Exception as e:
                print(f"⚠️ Could not mux subtitles: {e}")
            
    else:
        print(f"❌ Composition failed: {result.error}")

if __name__ == "__main__":
    main()
