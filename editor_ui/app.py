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
CLIPS_DIR     = WORKSPACE_DIR / "clips"

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
    return jsonify({"ok": True, "count": len(segs)})

@app.route("/api/build", methods=["POST"])
def api_build():
    global build_status
    if BUILD_LOCK.locked():
        return jsonify({"ok": False, "message": "Build already in progress"}), 409

    segs = load_segments()
    if not segs:
        return jsonify({"ok": False, "message": "No segments to build"}), 400

    def _run():
        global build_status
        build_status = {"running": True, "message": "Trimming and stitching clips...", "done": False, "error": ""}
        with BUILD_LOCK:
            try:
                build_reel_from_segments(segs, CLIPS_DIR, REEL_PATH)
                build_status = {"running": False, "message": "Reel built successfully!", "done": True, "error": ""}
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
