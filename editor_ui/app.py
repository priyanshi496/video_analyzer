"""
editor_ui/app.py — Flask server for the Web UI.
Handles file uploads, analysis, and the reel editor.
"""

import json
import os
import threading
import logging
from pathlib import Path
from werkzeug.utils import secure_filename

# Silence OpenCV internal FFmpeg/HEVC decoder warning spam
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"

from flask import Flask, render_template, jsonify, request, send_file, abort

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONFIG
from pipeline import get_video_info, run_full_analysis, analyze_single_segment
from quality import analyze_all_videos_quality
from stitch import build_reel_from_segments

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = str(Path(__file__).resolve().parent.parent / "input_videos")
app.config['MAX_CONTENT_LENGTH'] = 1000 * 1024 * 1024  # 1GB limit

# State
WORKSPACE_DIR = Path(__file__).resolve().parent.parent
SEGMENTS_PATH = WORKSPACE_DIR / CONFIG["segments_json"]
REEL_PATH     = WORKSPACE_DIR / CONFIG["reel_filename"]
CLIPS_DIR         = WORKSPACE_DIR / "clips"
POLISH_PATH       = WORKSPACE_DIR / "polish_settings.json"

BUILD_LOCK = threading.Lock()
build_status = {"running": False, "message": "", "done": False, "error": ""}

ANALYSIS_LOCK = threading.Lock()
analysis_status = {"running": False, "message": "", "progress": 0, "done": False, "error": ""}


# ── Helpers ────────────────────────────────────────────────────────────────────

def load_segments() -> list:
    if SEGMENTS_PATH.exists():
        return json.loads(SEGMENTS_PATH.read_text())
    return []

ACTIVE_SEGMENTS_PATH = WORKSPACE_DIR / "active_segments.json"

def save_segments(segs: list):
    SEGMENTS_PATH.write_text(json.dumps(segs, indent=2))
    # Always keep active_segments.json in sync — only the clips with is_used=True
    active = sorted(
        [s for s in segs if s.get("is_used", False)],
        key=lambda x: x.get("story_position", 9999)
    )
    ACTIVE_SEGMENTS_PATH.write_text(json.dumps(active, indent=2))

def get_uploaded_videos() -> list:
    Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)
    files = []
    for p in Path(app.config['UPLOAD_FOLDER']).iterdir():
        if p.suffix.lower() in {
            ".mp4", ".mov", ".mkv", ".avi", ".webm",
            ".jpg", ".jpeg", ".png", ".heic"
        }:
            files.append(str(p))
    return sorted(files)

def sync_to_remotion_composer():
    composer_my_reel = WORKSPACE_DIR / "OpenMontage" / "remotion-composer" / "src" / "my_reel.json"
    try:
        # 1. Load active segments
        segs = load_segments()
        active = sorted(
            [s for s in segs if s.get("is_used", True) is not False],
            key=lambda x: x.get("story_position", 9999)
        )
        
        # 2. Load polish settings
        polish_data = load_polish()
        
        # 3. Read transitions, captions, style and position
        caption_style = "cinematic"
        caption_position = "bottom"
        caption_mode = polish_data.get("caption_mode", "per-clip")
        
        # Read defaults from directives if they exist
        directives_path = WORKSPACE_DIR / "directives.txt"
        if directives_path.exists():
            try:
                directives_text = directives_path.read_text(encoding="utf-8")
                directives_lower = directives_text.lower()
                
                import re
                match = re.search(r'(?i)Caption style:\s*(.*)', directives_text)
                if match:
                    caption_style = match.group(1).strip()
                
                if "top of te reel" in directives_lower or "top of the reel" in directives_lower or "place at top-center" in directives_lower or "caption position: top" in directives_lower:
                    caption_position = "top"
            except Exception:
                pass

        # Then let polish settings override them (highest priority)
        if "caption_style" in polish_data:
            caption_style = polish_data["caption_style"]
        if "caption_position" in polish_data:
            caption_position = polish_data["caption_position"]
        caption_color = polish_data.get("caption_color", "")
        
        # Per-style color overrides (new: preferred over legacy single caption_color)
        caption_style_colors = polish_data.get("caption_style_colors", {})
        # Determine the color to apply for this render: use per-style color if set,
        # otherwise fall back to the legacy global color
        style_specific_color = caption_style_colors.get(caption_style, "") if caption_style_colors else ""
        effective_caption_color = style_specific_color or caption_color

        single_caption_text = None
        if caption_mode == "single" and polish_data.get("captions"):
            single_caption_text = polish_data["captions"][0] if len(polish_data["captions"]) > 0 else ""

        # 4. Build cuts list
        cuts = []
        
        # Try to locate the trimmed clip from the latest run to reuse it if possible.
        runs_dir = WORKSPACE_DIR / "projects" / "my-reel" / "runs"
        latest_run = None
        latest_time = 0
        if runs_dir.exists():
            for d in runs_dir.iterdir():
                if d.is_dir() and d.name.startswith("run_"):
                    t = d.stat().st_mtime
                    if t > latest_time:
                        latest_time = t
                        latest_run = d

        # Check if we can reuse the pre-trimmed clips from the latest run
        reuse_trimmed = False
        latest_decisions = None
        if latest_run:
            latest_decisions_path = latest_run / "edit_decisions.json"
            if latest_decisions_path.exists():
                try:
                    with open(latest_decisions_path, "r", encoding="utf-8") as lf:
                        latest_decisions = json.load(lf)
                    # Check if the number of cuts is identical
                    if len(latest_decisions.get("cuts", [])) == len(active):
                        # Verify that the durations of all cuts match the active segments
                        durations_match = True
                        for idx, seg in enumerate(active):
                            seg_dur = float(seg.get("end_sec", 0.0)) - float(seg.get("start_sec", 0.0))
                            cut_dur = float(latest_decisions["cuts"][idx].get("out_seconds", 0.0)) - float(latest_decisions["cuts"][idx].get("in_seconds", 0.0))
                            if abs(seg_dur - cut_dur) > 0.1:
                                durations_match = False
                                break
                        if durations_match:
                            reuse_trimmed = True
                except Exception:
                    pass

        for i, seg in enumerate(active):
            source_path = seg.get("video_path")
            in_s = float(seg.get("start_sec", 0.0))
            out_s = float(seg.get("end_sec", 3.0))
            duration = out_s - in_s
            
            if reuse_trimmed and latest_run:
                trimmed_clip = latest_run / "trimmed" / f"clip_{i}_trimmed.mp4"
                if trimmed_clip.exists():
                    source_path = str(trimmed_clip)
                    in_s = 0.0
                    out_s = duration
                        
            t_out = "cut"
            t_dur = 0.0
            if "transitions" in polish_data and i < len(polish_data["transitions"]):
                t_val = polish_data["transitions"][i]
                if t_val and t_val != "cut":
                    t_out = t_val
                    t_dur = 0.5
                    
            if i == len(active) - 1:
                t_out = "fade"
                t_dur = 1.0
                
            cap_text = ""
            if caption_style != "none":
                if single_caption_text is not None:
                    cap_text = single_caption_text
                elif "captions" in polish_data and i < len(polish_data["captions"]):
                    cap_text = polish_data["captions"][i] or ""
                else:
                    cap_text = seg.get("captionText", "")
                    
            cut_obj = {
                "id": f"cut_{i}",
                "source": source_path,
                "in_seconds": in_s,
                "out_seconds": out_s,
                "transition_out": t_out,
                "transition_duration": t_dur,
                "captionText": cap_text,
                "captionPosition": caption_position,
                "captionStyle": caption_style,
                "captionColor": effective_caption_color
            }
            cuts.append(cut_obj)
            
        # 5. Build audio soundtrack config
        audio_config = {}
        music_settings = polish_data.get("music", {})
        
        bgm_path = None
        if latest_run:
            run_bgm = latest_run / "audio" / "bgm.mp3"
            if run_bgm.exists():
                bgm_path = str(run_bgm)
                
        if not bgm_path:
            preview_bgm = WORKSPACE_DIR / "projects" / "my-reel" / "preview_bgm.mp3"
            if preview_bgm.exists():
                bgm_path = str(preview_bgm)
                
        if bgm_path:
            bgm_volume = float(music_settings.get("volume", 40)) / 100.0
            bgm_offset = float(music_settings.get("offset", 0.0))
            audio_config["music"] = {
                "asset_id": bgm_path,
                "volume": bgm_volume,
                "trimBeforeSeconds": bgm_offset,
                "ducking": True
            }
            
        reel_data = {
            "version": "1.0",
            "render_runtime": "ffmpeg",
            "cuts": cuts
        }
        if audio_config:
            reel_data["audio"] = audio_config
            
        def _to_file_uri(p: str) -> str:
            if not p or p.startswith(("http://", "https://", "file://")):
                return p
            resolved = Path(p).resolve()
            if resolved.exists():
                posix = resolved.as_posix()
                return f"file:///{posix}" if not posix.startswith("/") else f"file://{posix}"
            return p

        for cut in reel_data.get("cuts", []):
            if cut.get("source"):
                cut["source"] = _to_file_uri(cut["source"])
                
        if "audio" in reel_data and "music" in reel_data["audio"]:
            music = reel_data["audio"]["music"]
            if music.get("asset_id"):
                music["asset_id"] = _to_file_uri(music["asset_id"])
                music["src"] = music["asset_id"]
                
        with open(composer_my_reel, "w", encoding="utf-8") as f:
            json.dump(reel_data, f, indent=2)
        logging.info(f"✅ Hot-synced my_reel.json to Remotion composer")
    except Exception as e:
        logging.exception(f"Failed to hot-sync to Remotion composer: {e}")

# ── Routes: Pages ──────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/editor")
def editor():
    return render_template("editor.html")

# ── Routes: Upload & Analysis ──────────────────────────────────────────────────

@app.route("/api/upload", methods=["POST"])
def api_upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "No file part"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "No selected file"}), 400
    
    if file:
        Path(app.config['UPLOAD_FOLDER']).mkdir(exist_ok=True)
        filename = secure_filename(file.filename)
        path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(path)
        return jsonify({"ok": True, "filename": filename})

@app.route("/api/files")
def api_files():
    files = get_uploaded_videos()
    return jsonify({"files": [Path(f).name for f in files]})

@app.route("/api/reset", methods=["POST"])
def api_reset():
    import shutil
    try:
        # 1. Clear LLM Analysis Cache
        cache_path = WORKSPACE_DIR / "logs" / "analysis_cache.json"
        if cache_path.exists():
            cache_path.unlink()

        # 2. Clear Selected Segments Metadata
        if SEGMENTS_PATH.exists():
            SEGMENTS_PATH.unlink()

        # 3. Clear Output Reel
        if REEL_PATH.exists():
            REEL_PATH.unlink()

        # 4. Clear Timeline Frame Images
        frames_dir = WORKSPACE_DIR / "timeline_frames"
        if frames_dir.exists():
            shutil.rmtree(frames_dir)
        frames_dir.mkdir(exist_ok=True)

        # 5. Clear Trimmed Clip Highlights
        if CLIPS_DIR.exists():
            shutil.rmtree(CLIPS_DIR)
        CLIPS_DIR.mkdir(exist_ok=True)

        # 6. Clear Raw Input Videos
        upload_folder = Path(app.config['UPLOAD_FOLDER'])
        if upload_folder.exists():
            for p in upload_folder.iterdir():
                if p.is_file() and p.suffix.lower() in {
                    ".mp4", ".mov", ".mkv", ".avi", ".webm",
                    ".jpg", ".jpeg", ".png", ".heic"
                }:
                    p.unlink()

        # 7. Clear the logs
        log_file = WORKSPACE_DIR / "analyzer.log"
        if log_file.exists():
            open(log_file, "w").close()

        # 8. Clear Polish Settings
        if POLISH_PATH.exists():
            POLISH_PATH.unlink()

        # 9. Clear Directives File
        directives_file = WORKSPACE_DIR / "directives.txt"
        if directives_file.exists():
            directives_file.unlink()

        # 10. Clear/Reset Remotion composer my_reel.json
        try:
            composer_my_reel = WORKSPACE_DIR / "OpenMontage" / "remotion-composer" / "src" / "my_reel.json"
            with open(composer_my_reel, "w", encoding="utf-8") as f:
                json.dump({"version": "1.0", "cuts": []}, f, indent=2)
        except Exception as e:
            logging.warning(f"Failed to reset Remotion composer my_reel.json: {e}")

        # Reset building and analysis statuses
        global build_status, analysis_status
        build_status = {"running": False, "message": "", "done": False, "error": ""}
        analysis_status = {"running": False, "message": "", "progress": 0, "done": False, "error": ""}

        return jsonify({"ok": True, "message": "Workspace reset successfully."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    global analysis_status
    if ANALYSIS_LOCK.locked():
        return jsonify({"ok": False, "error": "Analysis already running"}), 409

    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "error": "API Key (NVIDIA_API_KEY or OPENROUTER_API_KEY) not found in .env"}), 400

    videos = get_uploaded_videos()
    if not videos:
        return jsonify({"ok": False, "error": "No videos uploaded"}), 400

    from flask import request
    req_data = request.get_json(silent=True) or {}
    directives = req_data.get("directives", "")
    use_uploaded_order = req_data.get("use_uploaded_order", False)

    def _run_analysis():
        global analysis_status
        # Clear the log file so the UI terminal starts fresh for this run
        log_file = WORKSPACE_DIR / "analyzer.log"
        if log_file.exists():
            open(log_file, "w").close()
            
        # Save directives so the builder/music AI can read it later
        if directives:
            (WORKSPACE_DIR / "directives.txt").write_text(directives)
        elif (WORKSPACE_DIR / "directives.txt").exists():
            (WORKSPACE_DIR / "directives.txt").unlink()
            
        with ANALYSIS_LOCK:
            try:
                analysis_status = {"running": True, "message": "Extracting metadata...", "progress": 10, "done": False, "error": ""}
                
                raw_infos = [get_video_info(v) for v in videos]
                video_infos = [v for v in raw_infos if v is not None]
                
                if not video_infos:
                    raise ValueError("No valid videos could be read.")
                
                analysis_status = {"running": True, "message": "Running optical flow quality check...", "progress": 30, "done": False, "error": ""}
                video_quality_map = analyze_all_videos_quality(video_infos)
                
                analysis_status = {"running": True, "message": "Analyzing moments with AI...", "progress": 60, "done": False, "error": ""}
                ordered_segments, _ = run_full_analysis(video_infos, api_key, video_quality_map, [], directives=directives, use_uploaded_order=use_uploaded_order)
                
                save_segments(ordered_segments)
                
                analysis_status = {"running": True, "message": "Building initial reel...", "progress": 90, "done": False, "error": ""}
                build_reel_from_segments(ordered_segments, CLIPS_DIR, REEL_PATH)
                
                analysis_status = {"running": False, "message": "Done!", "progress": 100, "done": True, "error": ""}
            except Exception as e:
                analysis_status = {"running": False, "message": "", "progress": 0, "done": False, "error": str(e)}

    threading.Thread(target=_run_analysis, daemon=True).start()
    return jsonify({"ok": True, "message": "Analysis started"})

@app.route("/api/analyze_status")
def api_analyze_status():
    return jsonify(analysis_status)

@app.route("/media/<path:filename>")
def serve_media(filename):
    path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    if os.path.exists(path):
        return send_file(path)
    return abort(404)

@app.route("/api/logs")
def api_logs():
    log_file = WORKSPACE_DIR / "analyzer.log"
    if not log_file.exists():
        return jsonify({"logs": ""})
    try:
        with open(log_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
            return jsonify({"logs": "".join(lines[-200:])})
    except Exception as e:
        return jsonify({"logs": f"Error reading logs: {e}"})

# ── Routes: Editor ─────────────────────────────────────────────────────────────

@app.route("/api/segments")
def api_segments():
    return jsonify(load_segments())

@app.route("/api/videos")
def api_videos():
    files = get_uploaded_videos()
    raw_infos = [get_video_info(v) for v in files]
    infos = [v for v in raw_infos if v is not None]
    return jsonify([{"path": v["path"], "duration_sec": v["duration_sec"], "video_idx": idx} for idx, v in enumerate(infos)])

@app.route("/api/analyze_manual_clip", methods=["POST"])
def api_analyze_manual_clip():
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return jsonify({"ok": False, "error": "API Key (NVIDIA_API_KEY or OPENROUTER_API_KEY) not found in .env"}), 400

    data = request.get_json()
    video_path = data.get("video_path")
    start_sec = float(data.get("start_sec", 0.0))
    end_sec = float(data.get("end_sec", 3.0))

    if not video_path:
        return jsonify({"ok": False, "error": "Missing video_path"}), 400

    try:
        logging.info(f"⚡ Running custom manual clip AI analysis: {Path(video_path).name} from {start_sec}s to {end_sec}s")
        analysis = analyze_single_segment(video_path, start_sec, end_sec, api_key)
        return jsonify({"ok": True, "analysis": analysis})
    except Exception as e:
        logging.exception("Failed to analyze manual clip")
        return jsonify({"ok": False, "error": str(e)}), 500

@app.route("/api/update", methods=["POST"])
def api_update():
    data = request.get_json()
    segs = data.get("segments", [])
    save_segments(segs)
    sync_to_remotion_composer()
    return jsonify({"ok": True, "count": len(segs)})

@app.route("/api/build", methods=["POST"])
def api_build():
    global build_status
    if BUILD_LOCK.locked():
        return jsonify({"ok": False, "message": "Build already in progress"}), 409

    segs = load_segments()
    if not segs:
        return jsonify({"ok": False, "message": "No segments to build"}), 400

    # Ensure active_segments.json is in sync with latest edits
    save_segments(segs)

    def _run():
        global build_status
        build_status = {
            "running": True, 
            "message": "AI Director deciding transitions & music. Rendering cinematic reel in Remotion...", 
            "done": False, 
            "error": ""
        }
        with BUILD_LOCK:
            try:
                import subprocess
                import shutil
                
                cmd = [
                    str(WORKSPACE_DIR / ".venv" / "bin" / "python"),
                    str(WORKSPACE_DIR / "OpenMontage" / "generate_reel.py")
                ]
                
                # Execute cinematic generator
                res = subprocess.run(cmd, capture_output=True, text=True, cwd=str(WORKSPACE_DIR))
                
                # Log outputs to the UI log viewer
                log_file = WORKSPACE_DIR / "analyzer.log"
                with open(log_file, "a", encoding="utf-8") as lf:
                    lf.write("\n\n=== UI Build Triggered Cinematic Remotion Render ===\n")
                    lf.write(res.stdout)
                    if res.stderr:
                        lf.write("\n--- Error Output ---\n")
                        lf.write(res.stderr)
                
                if res.returncode != 0:
                    raise RuntimeError(f"Cinematic rendering failed. Code: {res.returncode}")

                # Locate the newly generated polished cinematic reel
                runs_dir = WORKSPACE_DIR / "projects" / "my-reel" / "runs"
                latest_run = None
                latest_time = 0
                if runs_dir.exists():
                    for d in runs_dir.iterdir():
                        if d.is_dir() and d.name.startswith("run_"):
                            t = d.stat().st_mtime
                            if t > latest_time:
                                latest_time = t
                                latest_run = d

                if not latest_run:
                    raise RuntimeError("No cinematic run folders found.")

                rendered_file = latest_run / "polished_cinematic_reel.mp4"
                if not rendered_file.exists():
                    raise RuntimeError(f"Rendered video missing at {rendered_file}")

                # Copy output to the Flask preview file path
                shutil.copy(str(rendered_file), str(REEL_PATH))
                
                build_status = {"running": False, "message": "Cinematic reel built successfully!", "done": True, "error": ""}
            except Exception as e:
                build_status = {"running": False, "message": "", "done": False, "error": str(e)}

    threading.Thread(target=_run, daemon=True).start()
    return jsonify({"ok": True, "message": "Build started"})

@app.route("/api/build_status")
def api_build_status():
    return jsonify(build_status)

@app.route("/download/reel")
def download_reel():
    if REEL_PATH.exists():
        return send_file(str(REEL_PATH), as_attachment=True, download_name="final_highlight_reel.mp4")
    abort(404)

@app.route("/preview/reel")
def preview_reel():
    if REEL_PATH.exists():
        return send_file(str(REEL_PATH), mimetype="video/mp4")
    abort(404)

@app.route("/preview/audio")
def preview_audio():
    settings = load_polish()
    music_settings = settings.get("music", {})
    genre = music_settings.get("genre", "cinematic_epic")
    if genre == "none" or not genre:
        abort(404)

    try:
        from OpenMontage.generate_reel import get_background_music
    except ImportError:
        abort(404)
        
    preview_path = WORKSPACE_DIR / "projects" / "my-reel" / "preview_bgm.mp3"
    is_user_custom = music_settings.get("is_user_custom", False)
    try:
        get_background_music(genre, str(preview_path), user_custom=is_user_custom)
        if preview_path.exists():
            return send_file(str(preview_path), mimetype="audio/mpeg")
    except Exception as e:
        print("Error previewing audio:", e)
        
    abort(404)


# ── Routes: Polish Settings ─────────────────────────────────────────────────────

_DEFAULT_POLISH = {
    "transitions": [],
    "volumes": [],
    "captions": [],
    "music": {"genre": "cinematic_epic", "volume": 40},
}


def load_polish() -> dict:
    if POLISH_PATH.exists():
        try:
            return json.loads(POLISH_PATH.read_text())
        except Exception:
            pass
    return dict(_DEFAULT_POLISH)


def save_polish_file(data: dict):
    POLISH_PATH.write_text(json.dumps(data, indent=2))


@app.route("/api/load_polish")
def api_load_polish():
    return jsonify(load_polish())


@app.route("/api/save_polish", methods=["POST"])
def api_save_polish():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False, "error": "No data"}), 400
    save_polish_file(data)
    sync_to_remotion_composer()
    return jsonify({"ok": True})
@app.route("/api/apply_polish", methods=["POST"])
def api_apply_polish():
    """AI-driven polish: picks transition types and music genre from segment data."""
    segs = load_segments()
    active = sorted(
        [s for s in segs if s.get("is_used", True) is not False],
        key=lambda x: x.get("story_position", 9999),
    )

    if not active:
        return jsonify({"ok": False, "error": "No active clips."}), 400

    # --- Read Directives once ---
    req_data = request.get_json(silent=True) or {}
    locked_song = (req_data.get("locked_song") or "").strip()
    
    directives_path = WORKSPACE_DIR / "directives.txt"
    directives_text = ""
    directives_lower = ""
    if directives_path.exists():
        try:
            directives_text = directives_path.read_text(encoding="utf-8")
            directives_lower = directives_text.lower()
        except Exception:
            pass
            
    # --- Parse Caption Style ---
    caption_style = "cinematic"
    if directives_text:
        import re
        match = re.search(r'(?i)Caption style:\s*(.*)', directives_text)
        if match:
            caption_style = match.group(1).strip()
    try:
        old_polish = load_polish()
        if old_polish and "caption_style" in old_polish:
            # Only use old style if no explicit match in new directives
            if not directives_text or "caption style:" not in directives_lower:
                caption_style = old_polish["caption_style"]
    except Exception:
        pass
            
    # --- Parse Volume from Directives ---
    current_volume = 40
    import re
    vol_match = re.search(r"music volume:\s*(\d+)", directives_lower)
    if vol_match:
        current_volume = int(vol_match.group(1))
    else:
        try:
            old_polish = load_polish()
            if old_polish and "music" in old_polish and "volume" in old_polish["music"]:
                current_volume = old_polish["music"]["volume"]
        except Exception:
            pass

    # --- Parse Single Caption Mode ---
    is_single_caption = "caption scope: single" in directives_lower
    caption_source = "ai"
    custom_caption_text = ""
    if is_single_caption:
        if "caption source: custom" in directives_lower:
            caption_source = "custom"
            for line in directives_text.splitlines():
                if line.lower().startswith("caption text:"):
                    custom_caption_text = line.split(":", 1)[1].strip()
                    break

    # --- Heuristic transition selection based on narrative role pairs ---
    TRANSITION_RULES = {
        ("hook",   "build"):   "fade",
        ("hook",   "clip"):    "fade",
        ("build",  "build"):   "cut",
        ("build",  "climax"):  "zoom_in",
        ("build",  "payoff"):  "dissolve",
        ("climax", "payoff"):  "zoom_out",
        ("payoff", "payoff"):  "fade",
        ("clip",   "clip"):    "cut",
        ("clip",   "climax"):  "zoom_in",
        ("manual", "manual"):  "cut",
    }
    DEFAULT_TRANSITION = "cut"

    transitions = []
    for i in range(len(active) - 1):
        a_role = (active[i].get("narrative_role") or active[i].get("story_role") or "clip").lower()
        b_role = (active[i + 1].get("narrative_role") or active[i + 1].get("story_role") or "clip").lower()
        t = TRANSITION_RULES.get((a_role, b_role)) or TRANSITION_RULES.get((b_role, a_role)) or DEFAULT_TRANSITION
        transitions.append(t)

    # --- Detect content style from ACTUAL CLIP CONTENT (what AI saw in the videos) ---
    clip_content_text = " ".join([
        (s.get("reason", "") + " " +
         s.get("what_happens", "") + " " +
         s.get("location_tag", "").replace("_", " ") + " " +
         s.get("overall_mood", "") + " " +
         s.get("overall_vibe", "") + " " +
         s.get("narrative_role", "") + " " +
         " ".join(s.get("primary_subjects", [])))
        for s in active
    ]).lower()

    is_travel_lifestyle = any(w in clip_content_text for w in [
        "travel", "nature", "scenic", "mountain", "beach", "road", "forest",
        "river", "landscape", "sky", "outdoor", "journey", "vacation", "trip",
        "explore", "hiking", "waterfall", "village", "sunset", "sunrise",
        "hills", "valley", "lake", "sea", "ocean", "ruins",
        "backpack", "wander", "roam", "cafe", "alley", "street", "walk",
        "lifestyle", "home", "cozy", "slow", "vlog", "daily"
    ])
    # Devotional detection — requires strong spiritual signals, NOT just "temple" alone
    # (temple alone is a travel keyword too; require at least 2+ devotional signals OR explicit spiritual words)
    _DEVOTIONAL_STRONG = [
        "devotional", "spiritual", "shiva", "bhajan", "prayer", "religious",
        "aarti", "mandir", "puja", "ritual", "sadhu", "monk", "incense",
        "holy", "sacred", "divine", "diya", "flame", "ganga",
        "shrine", "idol", "deity", "worship", "offering", "prasad", "priest", "pandit",
        "pilgrimage", "kirtan", "chant", "bell", "ghanta", "lamp", "arti", "pooja",
        "devotee", "faith", "blessing",
        "ashram", "math", "murti", "darshan",
        "krishna", "vishnu", "durga", "kali",
        "ganesh", "hanuman", "laxmi", "saraswati", "holy water",
        "agni", "fire ritual", "havan", "yagna", "spiritual gathering"
    ]
    _devotional_hit_count = sum(1 for w in _DEVOTIONAL_STRONG if w in clip_content_text)
    # Also check for temple + another religious signal together
    _has_temple = "temple" in clip_content_text
    is_devotional = (
        _devotional_hit_count >= 2 or
        (_devotional_hit_count >= 1 and _has_temple) or
        (directives_lower and any(w in directives_lower for w in [
            "spiritual", "devotional", "bhajan", "mantra", "divine", "sacred",
            "meditative", "meditation", "soulful", "worship", "prayer", "chant", "temple", "ganga"
        ]))
    )
    # Travel with temple is still travel-dominant if devotional signals are weak
    is_temple_travel = _has_temple and not is_devotional

    # --- Parse user mood/energy pill from directives (highest priority after locked_song) ---
    import re as _re
    _mood_match = _re.search(r"Mood/energy:\s*(\S+)", directives_text or "")
    user_mood = _mood_match.group(1).lower() if _mood_match else None
    # Also check raw keywords for backward compat
    mood_text = clip_content_text

    # Check if the user requested instrumental music or lyrical
    is_lyrical = "instrumental background music" not in directives_lower

    # Check if a specific instrumental genre was chosen
    _genre_match = _re.search(r"music genre:\s*(\S+)", directives_lower)
    user_genre = _genre_match.group(1).lower() if _genre_match else None

    # ─────────────────────────────────────────────────────────────────────────────
    # SONG SELECTION MATRIX — theme × user_mood → best song
    # Priority: locked_song > user_mood+theme > theme_only > generic_mood > fallback
    # ─────────────────────────────────────────────────────────────────────────────
    import random

    # Song pools by theme and mood
    DEVOTIONAL_SONGS = {
        "energetic":    ["Jai Jai Shivshankar", "Deva Deva", "Kaun Hai Woh", "Bolo Har Har Har"],
        "cinematic":    ["Kaun Hai Woh", "Namo Namo", "Kailash Kher - Teri Deewani"],
        "motivational": ["Deva Deva", "Namo Namo", "Jai Jai Shivshankar"],
        "peaceful":     ["Anup Jalota - Achyutam Keshavam", "Sachet Tandon - Ram Siya Ram", "A.R. Rahman - Roobaroo", "Mohit Chauhan - Kun Faya Kun"],
        "chill":        ["Sachet Tandon - Ram Siya Ram", "Kailash Kher - Teri Deewani", "Mohit Chauhan - Kun Faya Kun", "Jubin Nautiyal - Mere Ghar Ram Aaye Hain"],
        "emotional":    ["Jubin Nautiyal - Mere Ghar Ram Aaye Hain", "Kailash Kher - Teri Deewani", "Sachet Tandon - Ram Siya Ram", "Mohit Chauhan - Kun Faya Kun"],
        "romantic":     ["A.R. Rahman - Roobaroo", "Pritam - Subhanallah", "Mohit Chauhan - Kun Faya Kun"],
        "fun":          ["Gajanana", "Deva Deva", "Bolo Har Har Har"],
        "default":      ["Namo Namo", "Deva Deva", "Sachet Tandon - Ram Siya Ram"],
    }
    TEMPLE_TRAVEL_SONGS = {
        "energetic":    ["Deva Deva", "Kaun Hai Woh", "Jai Jai Shivshankar"],
        "cinematic":    ["Namo Namo", "Kaun Hai Woh", "Kailash Kher - Teri Deewani"],
        "motivational": ["Namo Namo", "Deva Deva", "Arijit Singh - Ilahi"],
        "peaceful":     ["Mohit Chauhan - Phir Se Ud Chala", "A.R. Rahman - Roobaroo", "Pritam - Safar", "Mohit Chauhan - Kun Faya Kun"],
        "chill":        ["Amit Trivedi - Khaabon Ke Parindey", "Arijit Singh - Safar", "Arijit Singh - Ilahi", "Mohit Chauhan - Kun Faya Kun"],
        "emotional":    ["Arijit Singh - Ilahi", "Mohit Chauhan - Kun Faya Kun", "Pritam - Subhanallah"],
        "romantic":     ["Pritam - Subhanallah", "Arijit Singh - Ilahi", "Mohit Chauhan - Kun Faya Kun"],
        "fun":          ["Deva Deva", "Namo Namo", "Kanimaa"],
        "default":      ["Namo Namo", "Arijit Singh - Ilahi", "Arijit Singh - Safar"],
    }
    TRAVEL_SONGS = {
        "energetic":    ["Kanimaa", "Tauba Tauba", "Sher Khul Gaye"],
        "cinematic":    ["Arijit Singh - Ilahi", "Pritam - Safar", "Mohit Chauhan - Phir Se Ud Chala", "Udit Narayan - Yun Hi Chala Chal", "Arijit Singh - Kesariya"],
        "motivational": ["Sher Khul Gaye", "Arijit Singh - Ilahi", "Siddharth Mahadevan - Zinda"],
        "peaceful":     ["Amit Trivedi - Khaabon Ke Parindey", "Pritam - Safar", "Anuv Jain - Alag Aasmaan"],
        "chill":        ["Amit Trivedi - Khaabon Ke Parindey", "Anuv Jain - Husn", "Pritam - Safar"],
        "emotional":    ["Arijit Singh - Ilahi", "Pritam - Subhanallah", "Arijit Singh - Apna Bana Le"],
        "romantic":     ["Pritam - Subhanallah", "Arijit Singh - Ilahi", "Arijit Singh - O Maahi"],
        "fun":          ["Tauba Tauba", "Kanimaa", "Arijit Singh - What Jhumka"],
        "default":      ["Arijit Singh - Ilahi", "Pritam - Safar", "Mohit Chauhan - Phir Se Ud Chala"],
    }
    GENERIC_MOOD_SONGS = {
        "energetic":    ["upbeat_pop", "Tauba Tauba", "Kanimaa"],
        "cinematic":    ["cinematic_epic", "Arijit Singh - Ilahi"],
        "motivational": ["upbeat_pop", "Sher Khul Gaye"],
        "peaceful":     ["chill_lofi", "travel_acoustic"],
        "chill":        ["chill_lofi", "Amit Trivedi - Khaabon Ke Parindey"],
        "emotional":    ["romantic_orchestral", "Arijit Singh - Ilahi"],
        "romantic":     ["romantic_orchestral", "Pritam - Subhanallah"],
        "fun":          ["upbeat_pop", "Tauba Tauba"],
        "default":      ["cinematic_epic"],
    }

    def _pick_song(pool_dict, mood_key):
        """Pick a random song from the pool matching mood_key, fallback to 'default'."""
        options = pool_dict.get(mood_key) or pool_dict.get("default", ["cinematic_epic"])
        return random.choice(options)

    if locked_song:
        genre = locked_song
        print(f"🔒 Locked custom song from UI: '{genre}' — skipping AI music selection.")
    elif not is_lyrical:
        # Instrumental mode!
        if user_genre:
            GENRE_MAP = {
                "lofi": "chill_lofi",
                "acoustic": "travel_acoustic",
                "classical": "romantic_orchestral",
                "pop": "upbeat_pop",
                "edm": "edm_beat",
                "bollywood": "bollywood instrumental",
                "punjabi": "punjabi instrumental"
            }
            genre = GENRE_MAP.get(user_genre, user_genre)
            print(f"🎵 Instrumental mode: user selected genre pill '{user_genre}' → mapped to '{genre}'")
        else:
            effective_mood = user_mood or (
                "energetic" if any(w in directives_lower for w in ["energetic", "energic", "upbeat", "fast", "hype"]) else
                "peaceful" if any(w in mood_text for w in ["serene", "calm", "peaceful", "contemplative", "reverent", "meditative"]) else
                "cinematic" if any(w in mood_text for w in ["epic", "climax", "adventure", "vast", "mountain", "scenic", "dramatic"]) else
                "default"
            )
            MOOD_INSTRUMENTAL_MAP = {
                "energetic": "upbeat_pop",
                "motivational": "upbeat_pop",
                "fun": "upbeat_pop",
                "cinematic": "cinematic_epic",
                "peaceful": "chill_lofi",
                "chill": "chill_lofi",
                "romantic": "romantic_orchestral",
                "emotional": "romantic_orchestral",
                "default": "travel_acoustic"
            }
            genre = MOOD_INSTRUMENTAL_MAP.get(effective_mood, "travel_acoustic")
            print(f"🎵 Instrumental mode: auto-picked mood '{effective_mood}' → '{genre}'")
    else:
        # Lyrical mode! Pick from theme pools
        if is_devotional:
            # Strong devotional/spiritual content — pick from devotional pool based on user mood
            effective_mood = user_mood or (
                "energetic" if any(w in directives_lower for w in ["energetic", "energic", "upbeat", "fast", "hype"]) else
                "peaceful" if any(w in mood_text for w in ["serene", "calm", "peaceful", "contemplative", "reverent", "meditative"]) else
                "cinematic" if any(w in mood_text for w in ["epic", "climax", "adventure", "vast", "mountain"]) else
                "energetic" if any(w in mood_text for w in ["fire", "intense", "ceremony", "aarti", "ritual"]) else
                "default"
            )
            genre = _pick_song(DEVOTIONAL_SONGS, effective_mood)
            print(f"🕌 Devotional content detected. User mood='{effective_mood}' → '{genre}'")
        elif is_temple_travel:
            # Temple in a travel context — blend devotional + travel based on user mood
            effective_mood = user_mood or (
                "cinematic" if any(w in directives_lower for w in ["cinematic", "epic", "dramatic"]) else
                "peaceful" if any(w in directives_lower for w in ["chill", "lofi", "peaceful", "soft"]) else
                "default"
            )
            genre = _pick_song(TEMPLE_TRAVEL_SONGS, effective_mood)
            print(f"🛕 Temple travel content detected. User mood='{effective_mood}' → '{genre}'")
        elif is_travel_lifestyle:
            # Travel/outdoor content — pick from travel pool based on user mood
            effective_mood = user_mood or (
                "energetic" if any(w in directives_lower for w in ["energetic", "energic", "upbeat", "hype"]) else
                "chill" if any(w in directives_lower for w in ["chill", "lofi", "lo-fi"]) else
                "romantic" if any(w in directives_lower for w in ["romantic", "emotional"]) else
                "cinematic" if any(w in directives_lower for w in ["cinematic", "epic", "dramatic"]) else
                "default"
            )
            genre = _pick_song(TRAVEL_SONGS, effective_mood)
            print(f"✈️ Travel content detected. User mood='{effective_mood}' → '{genre}'")
        elif directives_lower and any(w in directives_lower for w in ["hindi", "bolly", "bollywood"]):
            if any(w in directives_lower for w in ["party", "energetic", "hype", "promo", "event", "dance"]):
                if any(w in mood_text for w in ["bike", "riding", "ride", "travel", "journey"]):
                    genre = "Kanimaa"
                elif any(w in mood_text for w in ["winner", "climax", "payoff", "celebration"]):
                    genre = "Sher Khul Gaye"
                else:
                    genre = "Tauba Tauba"
            elif any(w in directives_lower for w in ["chill", "lofi", "lo-fi"]):
                genre = "Amit Trivedi - Khaabon Ke Parindey"
            else:
                genre = "Arijit Singh - Ilahi"
        else:
            # Generic content — user mood pill drives selection
            effective_mood = user_mood or (
                "energetic" if any(w in directives_lower for w in ["energetic", "energic", "upbeat"]) else
                "chill" if any(w in directives_lower for w in ["chill", "lofi", "lo-fi"]) else
                "romantic" if any(w in directives_lower for w in ["romantic", "emotional"]) else
                "cinematic" if any(w in directives_lower for w in ["cinematic", "epic", "scenery", "dramatic"]) else
                "cinematic" if any(w in mood_text for w in ["epic", "cinematic", "dramatic", "adventure"]) else
                "chill" if any(w in mood_text for w in ["chill", "calm", "peaceful", "serene", "relaxing"]) else
                "energetic" if any(w in mood_text for w in ["energetic", "exciting", "thrilling", "action", "fast"]) else
                "default"
            )
            genre = _pick_song(GENERIC_MOOD_SONGS, effective_mood)
            print(f"🎵 Generic content. User mood='{effective_mood}' → '{genre}'")

        # Map instrumental placeholders to vocal songs if lyrical mode is active
        INSTRUMENTAL_TO_VOCAL = {
            "cinematic_epic": "Arijit Singh - Ilahi",
            "travel_acoustic": "Pritam - Safar",
            "chill_lofi": "Amit Trivedi - Khaabon Ke Parindey",
            "romantic_orchestral": "Pritam - Subhanallah",
            "upbeat_pop": "Tauba Tauba"
        }
        if genre in INSTRUMENTAL_TO_VOCAL:
            old_genre = genre
            genre = INSTRUMENTAL_TO_VOCAL[genre]
            print(f"🔄 Lyrical mode active: Replaced instrumental placeholder '{old_genre}' with vocal song '{genre}'")

    # --- Default volumes ---
    volumes  = [100] * len(active)
    
    # --- Generate Captions using Text LLM ---
    if is_devotional:
        if is_single_caption:
            captions = ["came to see the temple | left actually changed"] * len(active)
        else:
            captions = [
                "came to see the temple | left actually changed" if i % 2 == 0 
                else "didn't plan to stay for aarti | couldn't leave after" 
                for i in range(len(active))
            ]
    else:
        captions = [""] * len(active)
    
    # If custom single caption, no need to ask LLM for captions
    if is_single_caption and caption_source == "custom":
        captions = [custom_caption_text] * len(active)
        caption_system = ""
        prompt_instruction = "Do not generate captions, just pick transitions and song."
        expected_json = '{\n  "transitions": ["fade", "dissolve"],\n  "trending_song": "Artist - Song Name"\n}'
    else:
        BASE_CAPTION_SYSTEM = """
You write captions for Instagram reels that people actually save and share.

THE GOLDEN RULE: Two lines that work as a pair — line 1 sets up, line 2 lands.
Use exactly ONE pipe '|' to split them.

FORMATS THAT GO VIRAL:
1. Contrast: "came for the photo | stayed for the feeling"
2. Earned admission: "didn't expect to cry here | but the ghats had other plans"
3. Casual + deep: "stopped for 10 mins | it's been 3 hours"
4. Specific detail: "the 4am aarti hits different | when you actually show up"
5. Ironic: "came to see the temple | left questioning everything"
6. Dry humor: "unhinged decision | 0 regrets"
7. Honest + simple: "the beach, the dress | best call honestly"

VOICE CHECK: Would a real person text this to a friend?
If it sounds like a poem or Canva quote, rewrite it.

RULES:
- Write in ENGLISH ONLY. No Hindi, no Romanized Hindi, no mixed language.
- NEVER describe what's visually on screen — evoke how it FEELS
- NEVER sound like a translated Hindi song lyric
- NO hashtags, NO emojis, NO punctuation except the pipe
- Sounds like a real 22-year-old solo traveler, not a brand or AI

BANNED PHRASES (never use):
- anything with 'soul', 'heart takes off', 'silence hums', 'thoughts ripple'
- nature doing human things: 'wake paints', 'soul drinks', 'lake whispers'
- anything that could go on a sunset wallpaper
- two random aesthetic words smashed together
"""

        CATEGORY_INJECT = {
            "devotional": (
                "CONTEXT: Temple / spiritual / aarti experience.\n"
                "Tone: someone genuinely moved, not a tourist describing a monument.\n"
                "Examples: 'came to check it off | left actually changed'\n"
                "         'didn't plan to stay for aarti | couldn't leave after'\n"
                "         'the bells, the smoke, the crowd | nothing prepares you'\n"
            ),
            "temple_travel": (
                "CONTEXT: Travel content that includes temples or spiritual places.\n"
                "Tone: wanderer with quiet reverence — not fully devotional, not fully tourist.\n"
                "Examples: 'thought it was just a temple | it wasn't just a temple'\n"
                "         'showed up for the architecture | stayed for the feeling'\n"
            ),
            "travel": (
                "CONTEXT: Travel, outdoor, or lifestyle content.\n"
                "Tone: solo traveler, slightly philosophical, occasionally funny.\n"
                "Examples: 'said 10 minutes | it's been 2 hours'\n"
                "         'rice fields at 6am | nobody warned me'\n"
                "         'didn't plan this stop | best stop'\n"
            ),
            "generic": (
                "CONTEXT: General lifestyle content.\n"
                "Tone: relatable, slightly ironic, quietly real.\n"
                "Examples: 'didn't plan this | but here we are'\n"
                "         'came for content | left genuinely healed'\n"
            ),
        }

        category = (
            "devotional" if is_devotional else
            "temple_travel" if is_temple_travel else
            "travel" if is_travel_lifestyle else
            "generic"
        )
        if is_single_caption:
            length_rule = (
                "LENGTH: This is ONE caption for the whole reel. "
                "Each line can be 5-8 words — a complete thought is fine.\n"
            )
        else:
            length_rule = (
                "LENGTH: Max 3-4 words per line. Fragments only. But each fragment must carry a REAL thought or feeling.\n\n"
                "NOT two random aesthetic words.\n\n"
                "ANTI-PATTERN WARNING: Do NOT use 'X ki/ka/ke Y | Z ka/ki/ke W' structure for every caption. "
                "If more than 2 captions follow this pattern, you have failed. Vary the structure aggressively.\n\n"
                "USE THESE DIFFERENT STRUCTURES (one per caption, rotate):\n"
                "1. Reaction (e.g. 'didn't expect this | at all')\n"
                "2. Confession (e.g. 'stopped here | never leaving')\n"
                "3. Dry humor (e.g. 'unhinged decision | at 6am')\n"
                "4. Single punch (e.g. 'window seat. that's it. that's the caption')\n"
                "5. Honest take (e.g. 'the green dress was planned | the rain wasn't')\n"
                "6. Short punchy statement (e.g. 'windows down | completely ready')\n"
                "7. Time/specific (e.g. '7am river | nobody else there | perfection')\n\n"
                "CRITICAL WARNING: DO NOT COPY OR REUSE THE ABOVE EXAMPLE STRINGS LITERALLY. "
                "They are structural guidelines only. You MUST generate entirely unique content written specifically "
                "about the clip's actual Location, Subjects, and Action (e.g. do not write about 'green dress' unless the clip features a dress; "
                "do not write about 'rice fields' unless the clip features rice fields/fields).\n\n"
                "Each caption should feel like it came from a DIFFERENT moment of a real trip — "
                "not all written by the same poetic robot.\n"
            )

        caption_system = BASE_CAPTION_SYSTEM + "\n" + CATEGORY_INJECT[category] + "\n" + length_rule

        if is_single_caption:
            prompt_instruction = "1. Generate ONE SINGLE CAPTION that represents the vibe of the ENTIRE sequence of clips.\nOUTPUT: Return only the 1 caption line. Nothing else."
            expected_json = '{\n  "captions": ["YOUR | single caption"],\n  "transitions": ["fade", "dissolve"],\n  "trending_song": "Artist - Song Name"\n}'
        else:
            prompt_instruction = "1. Write one caption per clip following the style above.\nOUTPUT: Return only the caption line. Nothing else per caption."
            expected_json = '{\n  "captions": ["caption for clip 1", "caption for clip 2"],\n  "transitions": ["fade", "dissolve"],\n  "trending_song": "Artist - Song Name"\n}'

    try:
        from llm import call_openrouter_text
        from config import CONFIG
        import os, json, re
        
        if locked_song:
            song_instruction = (
                f"3. The user has manually selected '{locked_song}' as the background music. "
                f"Accept this choice and output \"trending_song\": \"{locked_song}\" exactly as given.\n"
            )
        else:
            # Enforce the dynamically/randomly selected song matching the theme and mood
            song_instruction = (
                f"3. The system has pre-selected the background music track/genre '{genre}' "
                f"matching the clip content and the user's mood preference of '{user_mood or 'not specified'}'. "
                f"You MUST output exactly this value: \"trending_song\": \"{genre}\" in your JSON response. "
                "Do not select or substitute any other song.\n"
            )

        if not is_lyrical and not locked_song:
            song_instruction = (
                f"3. CRITICAL: The user has requested INSTRUMENTAL background music only (no vocal songs/singing/lyrics). "
                f"The system pre-selected the instrumental genre/track '{genre}'. "
                f"You MUST output exactly this genre/keyword: '{genre}' as the \"trending_song\" in your JSON response.\n"
            )

        prompt = (
            f"{caption_system}\n\n"
            "USER EDITING DIRECTIVES (Custom Instructions):\n"
            f"{directives_text or 'focus on scenery'}\n\n"
            "I have an ordered sequence of video clips.\n\n"
            f"{prompt_instruction}\n\n"
            "Also:\n"
            "2. Choose a cinematic transition from each clip to the next. Valid transitions: cut, fade, dissolve, zoom_in, slide_left, slide_right. Use variety!\n"
            f"{song_instruction}"
            "Return ONLY valid JSON matching this exact structure:\n"
            f"{expected_json}\n\n"
            "Clips:\n"
        )
        for i, s in enumerate(active):
            desc = s.get("reason", "") or s.get("what_happens", "") or s.get("narrative_role", "clip")
            loc = s.get("location_tag", "").replace("_", " ")
            subj = ", ".join(s.get("primary_subjects", []))
            prompt += f"Clip {i+1}: Location: {loc}, Subjects: {subj}, Action: {desc}\n"
            
        text_model = CONFIG.get("story_order_model", "openrouter/owl-alpha")
        fallbacks = [CONFIG.get("story_order_fallback", "openai/gpt-oss-120b:free")]
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("NVIDIA_API_KEY")
        print("🤖 Generating cinematic captions, transitions, and trending BGM...")
        resp = call_openrouter_text(prompt, model=text_model, fallbacks=fallbacks, api_key=api_key, temperature=0.7)
        import re
        match = re.search(r"\{.*\}", resp, re.DOTALL)
        if match:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                if "captions" in parsed:
                    if is_single_caption and caption_source == "ai" and len(parsed["captions"]) > 0:
                        captions = [parsed["captions"][0]] * len(active)
                    elif len(parsed["captions"]) == len(active):
                        captions = parsed["captions"]
                if "transitions" in parsed and len(parsed["transitions"]) == len(active) - 1:
                    transitions = parsed["transitions"]
                
                # Only trust LLM song if there's no explicitly chosen Bollywood/Spiritual track from heuristics
                if not locked_song and "trending_song" in parsed and parsed["trending_song"]:
                    genre = parsed["trending_song"]
    except Exception as e:
        import logging
        logging.warning(f"Failed to generate AI captions: {e}")

    except Exception:
        pass

    polish = {
        "transitions": transitions,
        "volumes":     volumes,
        "captions":    captions,
        "music":       {"genre": genre, "volume": current_volume, "is_user_custom": bool(locked_song)},
        "caption_style": caption_style,
        "caption_mode": "single" if is_single_caption else "per-clip",
        "caption_position": "top" if ("top" in directives_lower or "place at top-center" in directives_lower or "top of te reel" in directives_lower or "top of the reel" in directives_lower) else "bottom",
    }
    save_polish_file(polish)
    sync_to_remotion_composer()

    return jsonify({
        "ok": True,
        "transitions": transitions,
        "captions":    captions,
        "music":       {"genre": genre, "volume": current_volume, "is_user_custom": bool(locked_song)},
        "caption_style": caption_style,
        "caption_mode": "single" if is_single_caption else "per-clip",
        "caption_position": "top" if ("top" in directives_lower or "place at top-center" in directives_lower or "top of te reel" in directives_lower or "top of the reel" in directives_lower) else "bottom",
        "clip_count":  len(active),
    })
