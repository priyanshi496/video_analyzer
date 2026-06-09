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

def get_background_music(query: str, output_path: str):
    """Scan local music library, search/download BGM using PixabayMusic, or fall back to SunoMusic."""
    # 1. First check the local music_library directory
    music_lib = workspace_root / "music_library"
    if music_lib.exists():
        tracks = list(music_lib.glob("*.mp3")) + list(music_lib.glob("*.wav"))
        if tracks:
            shutil.copy(str(tracks[0]), output_path)
            print(f"\n✅ Found and copied background music from library: {tracks[0].name}")
            return
    # 2. Try searching and downloading from Pixabay Music
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
        return
    
    print(f"⚠️ Pixabay download failed: {res.error}")
    
    # 3. Fallback to Suno AI music generation
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
            return
        else:
            print(f"⚠️ Suno AI generation failed: {res.error}")
    # 4. Fallback to public royalty-free MP3 download (sounds much better than a beep!)
    fallback_url = "https://www.chosic.com/wp-content/uploads/2021/07/Rain-and-Tears-chosic.com_.mp3"
    print(f"🎵 Downloading high-quality fallback travel music track from: {fallback_url}...")
    try:
        response = requests.get(fallback_url, timeout=30)
        response.raise_for_status()
        with open(output_path, "wb") as f:
            f.write(response.content)
        print(f"✅ Successfully downloaded high-quality fallback track!")
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
    prompt = f"""
    You are an expert film director. I am providing you with metadata and visual descriptions/captions for {len(clean_metadata)} sequential video clips in a highlight reel.
    
    1. Write a short, engaging voiceover script that spans the entire video (around 15-20 words max). 
    2. Write a short search query for downloading background music (BGM) based on the collective mood, vibe, and visual content of the clips.
    3. Decide the transitions between each clip based on their visual flow, descriptions, and location shifts.
    
    You have complete creative freedom for transitions! You can assign ANY transition effect you want (e.g., "cut", "crossfade", "fade", "wipeleft", "wiperight", "slideup", "circlecrop", "dissolve", "pixelize", "zoomin", "glitch", etc.).
    Do not just use "crossfade" for everything. Choose the most cinematic and appropriate transition for the visual flow between the two clips.
    
    Here is the clip sequence:
    {json.dumps(clean_metadata, indent=2)}
    
    OUTPUT FORMAT:
    You MUST output valid JSON ONLY, matching exactly this structure:
    {{
      "voiceover_script": "The journey begins as we take flight...",
      "bgm_search_query": "cinematic ambient travel",
      "transitions": [
        {{ "from": "clip_00", "to": "clip_01", "type": "crossfade", "duration": 0.5 }}
      ]
    }}
    """
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    
    data = {
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": "You are a precise JSON-only outputting API."},
            {"role": "user", "content": prompt}
        ],
        "response_format": {"type": "json_object"}
    }
    
    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
    if response.status_code != 200:
        print(f"❌ OpenRouter API error: {response.text}")
        sys.exit(1)
        
    content = response.json()["choices"][0]["message"]["content"]
    if content.startswith("```json"): content = content[7:-3]
    elif content.startswith("```"): content = content[3:-3]
        
    return json.loads(content)

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
        
    # Generate AI Decisions (OpenRouter)
    decisions = get_ai_decisions(clips_data)
    vo_text = decisions.get("voiceover_script", "A wonderful journey.")
    bgm_query = decisions.get("bgm_search_query", "calm travel music")
    ai_transitions = decisions.get("transitions", [])
    
    print("\n📝 AI Director Script:")
    print(f"   \"{vo_text}\"")
    
    # Feature Toggles
    enable_vo = False
    enable_bgm = os.getenv("ENABLE_BGM", "true").lower() == "true"
    enable_sub = False
    
    # Generate Audio Assets
    vo_path = str(AUDIO_DIR / "voiceover.wav")
    bgm_path = str(AUDIO_DIR / "bgm.mp3")
    srt_path = str(AUDIO_DIR / "voiceover.srt")
    vo_duration = 0.0
    
    if enable_vo:
        generate_voiceover(vo_text, vo_path)
        vo_duration = get_audio_duration(vo_path) if os.path.exists(vo_path) else 3.0
    
    if enable_bgm:
        get_background_music(bgm_query, bgm_path)
    
    if enable_sub and enable_vo:
        # Generate the SRT Subtitle file dynamically
        generate_srt_file(vo_text, vo_duration, 0.5, srt_path)

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
            
        # Extract dynamic transitions decided procedurally
        t_out = "cut"
        t_dur = 0.0
        current_clip_id = f"clip_{i:02d}"
        for trans in ai_transitions:
            if trans.get("from") == current_clip_id:
                t_out = trans.get("type", "cut")
                t_dur = float(trans.get("duration", 0.0))
                break
                
        # Fade out the very last clip as a cinematic outro
        if i == len(clips_data) - 1:
            t_out = "fade"
            t_dur = 1.0
            
        # PROBE ACTUAL DURATION to prevent trimming empty videos if the clips on disk are already pre-trimmed highlights
        in_s = float(clip.get("start_sec", 0.0))
        out_s = float(clip.get("end_sec", 3.0))
        
        try:
            probe_cmd = ["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", raw_path]
            probe_out = subprocess.check_output(probe_cmd, text=True)
            # Use the global json module
            import json as json_mod
            actual_dur = float(json_mod.loads(probe_out).get("format", {}).get("duration", out_s))
            if out_s > actual_dur:
                print(f"⚠️ Clip {raw_path} is shorter ({actual_dur:.1f}s) than requested end_sec ({out_s}s). Assuming pre-trimmed.")
                in_s = 0.0
                out_s = actual_dur
        except Exception:
            pass
        cuts.append({
            "id": f"cut_{i}",
            "source": raw_path,
            "in_seconds": in_s,
            "out_seconds": out_s,
            "transition_out": t_out,
            "transition_duration": t_dur
        })
    edit_decisions = {
        "version": "1.0",
        "render_runtime": "ffmpeg",
        "cuts": cuts
    }
    
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
            "volume": 0.3,
            "ducking": True
        }
        
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
                {"path": bgm_path, "role": "music", "volume": 0.3}
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
