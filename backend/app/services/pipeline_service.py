import logging
"""
pipeline.py — Main video analysis pipeline.

  1. Analyzes all videos in parallel threads (quality + LLM calls).
  2. Handles chunking for long videos.
  3. Merges adjacent segments with a configurable max_duration cap.
  4. Enforces story ordering via a text-only LLM call.
  5. Returns final ordered best_segments list ready for the editor UI.
"""

import time
import json
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from app.core.config import settings
from app.services.frames_service import extract_representative_frames, pick_frame_count, is_likely_black_clip
from app.services.llm_service import call_openrouter_multiimage, call_openrouter_text
from app.services.prompts_service import (
    build_timeline_prompt,
    build_story_order_prompt,
    parse_json_response,
    clamp_segments,
)
from app.services.logger_service import (
    init_run_log_dir,
    log_vision_call,
    log_story_order_call,
    write_run_summary,
)
from app.services.stitch_service import get_video_dimensions, get_video_rotation_metadata


CONFIG = {
    "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
    "fallback_models": [
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    ],
    "max_tokens_vision": 4096,
    "max_tokens_text":   1000,
    "story_order_model":    "openai/gpt-oss-120b:free",
    "story_order_fallback": "nvidia/nemotron-3-ultra-550b-a55b:free",
    # Two-step story context: vision analysis + narrative writing
    "story_vision_model":    "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",  # Step 1: NVIDIA NIM multiimage
    "story_narrative_model": "openrouter/owl-alpha",                            # Step 2: OpenRouter text
    "max_parallel_vision_calls": 3,
    "image_limit_per_request": 8,
    "max_reference_images": None,
    "chunk_window_sec":  45,
    "chunk_overlap_sec":  2,
    "min_request_gap_sec": 2.0,
    "max_retries":         3,
    "base_retry_sleep":    3.0,
    "quality_downsample_width": 360,
    "max_reel_sec": 60,
}
import threading

CACHE_FILE = Path("logs/analysis_cache.json")
CACHE_LOCK = threading.Lock()

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(cache: dict):
    try:
        CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        logging.warning(f"Failed to save cache: {e}")


import requests
import re
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

GEOCODE_CACHE = {}

def get_lat_lon_from_exif(image_path):
    try:
        image = Image.open(image_path)
        info = image._getexif()
        if not info: return None, None
        
        gps_info = None
        for tag, value in info.items():
            decoded = TAGS.get(tag, tag)
            if decoded == "GPSInfo":
                gps_info = {GPSTAGS.get(t, t): value[t] for t in value}
                break
                
        if not gps_info: return None, None
        
        def convert_to_degrees(value):
            d, m, s = value
            return float(d) + (float(m) / 60.0) + (float(s) / 3600.0)
            
        lat = lon = None
        if "GPSLatitude" in gps_info and "GPSLatitudeRef" in gps_info:
            lat = convert_to_degrees(gps_info["GPSLatitude"])
            if gps_info["GPSLatitudeRef"] != "N": lat = -lat
                
        if "GPSLongitude" in gps_info and "GPSLongitudeRef" in gps_info:
            lon = convert_to_degrees(gps_info["GPSLongitude"])
            if gps_info["GPSLongitudeRef"] != "E": lon = -lon
                
        return lat, lon
    except Exception:
        return None, None

def get_time_from_exif(image_path):
    try:
        image = Image.open(image_path)
        info = image._getexif()
        if not info: return None
        for tag, value in info.items():
            if TAGS.get(tag, tag) == "DateTimeOriginal":
                return value
    except Exception:
        pass
    return None

def reverse_geocode(lat, lon):
    if not lat or not lon: return None
    key = f"{round(lat, 3)},{round(lon, 3)}"
    if key in GEOCODE_CACHE: return GEOCODE_CACHE[key]
    
    url = f"https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lon}&format=json"
    headers = {"User-Agent": "VideoAnalyzerBot/1.0", "Accept-Language": "en"}
    try:
        r = requests.get(url, headers=headers, timeout=3)
        if r.status_code == 200:
            data = r.json()
            address = data.get("address", {})
            parts = []
            if "amenity" in address: parts.append(address["amenity"])
            elif "historic" in address: parts.append(address["historic"])
            elif "tourism" in address: parts.append(address["tourism"])
            
            if "city" in address: parts.append(address["city"])
            elif "town" in address: parts.append(address["town"])
            elif "village" in address: parts.append(address["village"])
            
            if "state" in address: parts.append(address["state"])
            if "country" in address: parts.append(address["country"])
            
            res = ", ".join(parts) if parts else data.get("display_name")
            GEOCODE_CACHE[key] = res
            return res
    except Exception as e:
        logging.warning(f"Geocode failed: {e}")
    return None

# ── Video Metadata ─────────────────────────────────────────────────────────────

def get_video_info(path: str) -> Optional[dict]:
    is_image = Path(path).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
    if is_image:
        import cv2
        img = cv2.imread(path)
        if img is not None:
            height, width = img.shape[:2]
        else:
            width, height = 1080, 1920
            
        lat, lon = get_lat_lon_from_exif(path)
        location_name = reverse_geocode(lat, lon)
        creation_time = get_time_from_exif(path)
        
        return {
            "path":         path,
            "duration_sec": 3.0,  # Fabricate 3.0s duration for static photo
            "width":        width,
            "height":       height,
            "fps":          30.0,
            "total_frames": 1,
            "is_image":     True,
            "location_name": location_name,
            "creation_time": creation_time,
        }

    try:
        cmd = ["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", path]
        out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode("utf-8")
        meta = json.loads(out)
    except Exception as e:
        logging.info(f"  ✗ ffprobe failed for {path}: {e} — skipping.")
        return None

    import cv2
    vs = next((s for s in meta["streams"] if s.get("codec_type") == "video"), None)
    if vs is None:
        logging.info(f"  ✗ No video stream in {path} — skipping.")
        return None

    duration = float(meta["format"].get("duration", 0) or 0)
    if duration < 0.5:
        logging.info(f"  ✗ duration={duration:.2f}s too short: {path} — skipping.")
        return None

    r_frame_rate = vs.get("r_frame_rate", "30/1")
    try:
        num, den = r_frame_rate.split("/")
        fps = float(num) / float(den) if float(den) != 0 else 30.0
    except Exception:
        fps = 30.0

    cap = cv2.VideoCapture(path)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()

    creation_time = meta.get("format", {}).get("tags", {}).get("creation_time")
    location_name = None
    loc_str = (

        meta.get("format", {}).get("tags", {}).get("location")
        or meta.get("format", {}).get("tags", {}).get("location-eng")
        or meta.get("format", {}).get("tags", {}).get("com.apple.quicktime.location.ISO6709")
    )
    if loc_str:
        import re
        match = re.search(r"([+-]\d+\.\d+)([+-]\d+\.\d+)", loc_str)
        if match:
            lat, lon = float(match.group(1)), float(match.group(2))
            location_name = reverse_geocode(lat, lon)



    return {
        "path":         path,
        "duration_sec": duration,
        "width":        int(vs.get("width", 0)),
        "height":       int(vs.get("height", 0)),
        "fps":          fps,
        "total_frames": total_frames,
        "creation_time": creation_time,
        "location_name": location_name,
    }


# ── Fallback Analysis ──────────────────────────────────────────────────────────

def _pick_best_quality_window(
    quality_samples: list,
    offset_sec: float,
    window_sec: float,
    clip_duration: float = 3.0,
) -> tuple:
    """
    When the LLM fails, use pre-computed quality data to find the single
    best short window (lowest shake + highest blur = sharpest steady moment).
    Returns (best_start, best_end) within the window [offset_sec, offset_sec+window_sec].
    """
    window_end = offset_sec + window_sec
    # Filter quality samples to those inside this chunk window
    relevant = [
        s for s in quality_samples
        if offset_sec <= s.get("t", 0) <= window_end
        and s.get("motion_type", "NORMAL") not in ("CHAOTIC", "WHIP_PAN")
    ]
    if not relevant:
        # No quality data — default to middle of window
        mid = offset_sec + window_sec / 2
        start = max(offset_sec, mid - clip_duration / 2)
        end   = min(window_end, start + clip_duration)
        return round(start, 2), round(end, 2)

    # Score each sample: reward sharpness (blur_norm), penalise shake
    def score(s):
        return s.get("blur_norm", 5) - s.get("shake_norm", 5) * 0.5

    best = max(relevant, key=score)
    center = best["t"]
    start  = max(offset_sec,  round(center - clip_duration / 2, 2))
    end    = min(window_end,  round(start  + clip_duration,     2))
    return start, end


def make_fallback_analysis(
    info: dict,
    offset_sec: float = 0.0,
    window_sec: float = None,
    video_quality_map: dict = None,
) -> dict:
    """
    Called when the LLM fails for a chunk.
    Tries to pick the BEST quality window using pre-computed optical flow data
    rather than blindly including the full window (which gets dropped later anyway).
    """
    window_sec = window_sec if window_sec is not None else info["duration_sec"]

    # Attempt quality-guided best-window selection
    q_samples = []
    if video_quality_map:
        q_samples = (video_quality_map.get(info["path"], {}) or {}).get("samples", [])

    clip_duration = 3.0
    if q_samples:
        start, end = _pick_best_quality_window(q_samples, offset_sec, window_sec, clip_duration)
        reason = "Quality-guided fallback: best SETTLED window selected from optical flow data (LLM unavailable)."
        summary = "[FALLBACK-QUALITY] LLM unavailable — best quality window auto-selected from shake/blur analysis."
        logging.info(f"  ⚡ Quality-guided fallback: selected {start}s–{end}s as best window in [{offset_sec:.1f}s–{offset_sec+window_sec:.1f}s]")
    else:
        # No quality data — take the first 3s of the window
        start = round(offset_sec, 2)
        end   = round(min(offset_sec + clip_duration, offset_sec + window_sec), 2)
        reason = "Fallback: API timeout, no quality data available."
        summary = "[FALLBACK] Model did not respond. Best-effort 3s window included."

    return {
        "video_summary":     summary,
        "camera_rotation":   0,
        "detected_scenario": "D",
        "key_moments":    [{"timestamp_sec": start, "description": "Quality-guided fallback window"}],
        "segments":       [{"start_sec": start, "end_sec": end, "what_happens": "Quality-guided fallback",
                            "keep": True,
                            "reason": reason}],
        "best_segments":  [{"start_sec": start, "end_sec": end,
                            "reason": reason,
                            "priority": 4, "narrative_role": "unknown",
                            "scenario_rule_applied": "Scenario D fallback — quality-guided",
                            "journey_phase": "unknown", "location_tag": "unknown",
                            "scene_category": "mixed", "primary_subjects": []}],
    }


# ── JSON Schema Definition & Repair ───────────────────────────────────────────

VISION_SCHEMA_DESC = """{
  "video_summary": "string describing the video contents",
  "camera_rotation": 0,
  "detected_scenario": "string (A|B|C|D|E|F)",
  "overall_mood": "string",
  "overall_vibe": "string",
  "editor_reasoning": "string",
  "key_moments": [
    {
      "timestamp_sec": float,
      "description": "string"
    }
  ],
  "best_segments": [
    {
      "start_sec": float,
      "end_sec": float,
      "what_happens": "string",
      "mood": "string",
      "energy": integer (1-10),
      "visual_quality": integer (1-10),
      "instagrammable": integer (1-10),
      "story_value": integer (1-10),
      "reason": "string",
      "priority": integer (1-5),
      "narrative_role": "string (setup|action|climax|reaction|payoff)",
      "clip_type_applied": "string",
      "location_tag": "string (snake_case)",
      "journey_phase": "string (approach|arrival|exterior|interior|detail|climax)",
      "time_of_day": "string (dawn|morning|afternoon|golden_hour|dusk|night|unknown)",
      "scene_category": "string (scenery|people|action|food|vehicle|mixed)",
      "primary_subjects": ["string"]
    }
  ]
}"""


def repair_json_output(bad_text: str, schema_desc: str, api_key: str) -> str:
    """
    Triggers a schema repair call to OpenRouter's text model asking it to parse and clean the corrupt payload.
    """
    prompt = f"""You are a JSON repair assistant.
We received a malformed, truncated, or incomplete JSON response from a vision model.
Your task is to parse, repair, and format this content into a strictly valid JSON object matching the target schema.

TARGET SCHEMA:
{schema_desc}

CORRUPT/MALFORMED JSON STRING:
{bad_text}

CRITICAL RULES:
1. Ensure the output is a single, valid JSON object matching the target schema.
2. The root object MUST contain the "best_segments" array. If "best_segments" is empty or missing, extract segment information from other keys (like "segments" or "moments") and map them to "best_segments".
3. Correct any missing closing brackets, brackets mismatch, trailing commas, or quotes.
4. Output ONLY the raw JSON string. Do NOT wrap it in markdown code blocks (like ```json) or add any conversational preamble.
"""
    text_model = CONFIG.get("story_order_model", "openrouter/owl-alpha")
    fallbacks = [CONFIG.get("story_order_fallback", "openai/gpt-oss-120b:free")]
    try:
        logging.info("  [Repair] Triggering LLM schema repair for malformed response...")
        return call_openrouter_text(prompt, model=text_model, fallbacks=fallbacks)
    except Exception as e:
        logging.warning(f"  ✗ Text-repair call failed: {e}")
        raise e


# ── Analyze One Window ─────────────────────────────────────────────────────────

def analyze_window(
    info: dict,
    offset_sec: float,
    window_sec: float,
    api_key: str,
    video_quality_map: dict,
    chunk_label: str = "",
    reference_paths: list = None,
    directives: str = "",
) -> tuple:
    """
    Analyze one time window. Returns (frame_meta, parsed_dict) — never None.
    """
    reference_paths = reference_paths or []
    n_frames   = pick_frame_count(window_sec)
    frame_meta = extract_representative_frames(
        info["path"], window_sec, n_frames,
        offset_sec=offset_sec, chunk_label=chunk_label
    )

    if not frame_meta:
        logging.info(f"  ✗ No frames for {info['path']} [{offset_sec}s–{offset_sec+window_sec:.1f}s] → quality-guided fallback")
        return [], make_fallback_analysis(info, offset_sec, window_sec, video_quality_map)

    limit     = CONFIG["image_limit_per_request"]
    ref_cap   = CONFIG["max_reference_images"]
    ref_slots = limit - len(frame_meta)
    if ref_cap is not None:
        ref_slots = min(ref_slots, ref_cap)
    ref_slots = max(ref_slots, 0)

    payload_images = [f["path"] for f in frame_meta] + reference_paths[:ref_slots]
    window_info    = dict(info, duration_sec=window_sec)
    ref_sent       = reference_paths[:ref_slots]
    prompt         = build_timeline_prompt(window_info, frame_meta, ref_sent, video_quality_map, directives)

    parsed = None
    raw = None

    # 1. Vision API Call (Retry max 2 attempts only on API connection/timeout errors)
    for attempt in range(1, 3):
        t0 = time.time()
        try:
            raw = call_openrouter_multiimage(payload_images, prompt, CONFIG["model"])
            duration = time.time() - t0
            # Log successful API call (will update parsed/errors later)
            log_vision_call(
                video_path=info["path"],
                model=CONFIG["model"],
                prompt=prompt,
                raw_response=raw or "",
                parsed=None,
                parse_error=None,
                attempt=attempt,
                duration_sec=duration,
                chunk_label=chunk_label,
            )
            break
        except Exception as e:
            duration = time.time() - t0
            log_vision_call(
                video_path=info["path"],
                model=CONFIG["model"],
                prompt=prompt,
                raw_response=raw or "",
                parsed=None,
                parse_error=str(e),
                attempt=attempt,
                duration_sec=duration,
                chunk_label=chunk_label,
            )
            if attempt < 2:
                logging.info(f"  ⚠️ Vision API attempt {attempt} failed: {e}. Retrying once...")
                time.sleep(3)
            else:
                logging.error(f"  ✗ Vision API calls failed after 2 attempts: {e}")

    # 2. JSON Parse & Repair (Only if raw response was successfully retrieved)
    if raw:
        t0 = time.time()
        try:
            parsed = parse_json_response(raw)
            if not isinstance(parsed, dict):
                raise ValueError("Parsed JSON is not a dictionary")
            parsed = auto_recover_segments(parsed)
            if not parsed.get("best_segments"):
                raise ValueError("Parsed JSON is missing required 'best_segments' key or the list is empty")
            
            # Log successful parsing
            duration = time.time() - t0
            log_vision_call(
                video_path=info["path"],
                model=CONFIG["model"],
                prompt=prompt,
                raw_response=raw,
                parsed=parsed,
                parse_error=None,
                attempt=1,
                duration_sec=duration,
                chunk_label=chunk_label,
            )
        except Exception as parse_err:
            logging.warning(f"  ⚠️ JSON parse/schema validation error: {parse_err}. Attempting schema repair...")
            try:
                repaired_raw = repair_json_output(raw, VISION_SCHEMA_DESC, api_key)
                parsed = parse_json_response(repaired_raw)
                if isinstance(parsed, dict):
                    parsed = auto_recover_segments(parsed)
                if isinstance(parsed, dict) and "best_segments" in parsed:
                    logging.info("  ✓ JSON successfully repaired by text model!")
                    # Log successful repaired parsing
                    duration = time.time() - t0
                    log_vision_call(
                        video_path=info["path"],
                        model=CONFIG["model"],
                        prompt=prompt,
                        raw_response=raw,
                        parsed=parsed,
                        parse_error=None,
                        attempt=1,
                        duration_sec=duration,
                        chunk_label=chunk_label,
                    )
                else:
                    raise ValueError("Repaired response still missing 'best_segments'")
            except Exception as repair_err:
                logging.warning(f"  ✗ JSON repair failed: {repair_err}")
                duration = time.time() - t0
                log_vision_call(
                    video_path=info["path"],
                    model=CONFIG["model"],
                    prompt=prompt,
                    raw_response=raw,
                    parsed=None,
                    parse_error=f"Parse Error: {parse_err} | Repair Error: {repair_err}",
                    attempt=1,
                    duration_sec=duration,
                    chunk_label=chunk_label,
                )

    if parsed is None:
        logging.info(f"  → Quality-guided fallback [{offset_sec}s–{offset_sec+window_sec:.1f}s] (LLM unavailable)")
        return frame_meta, make_fallback_analysis(info, offset_sec, window_sec, video_quality_map)

    return frame_meta, parsed


# ── Focus Directive & Filtering Helpers ────────────────────────────────────────

def parse_focus_directive(directives: str) -> dict:
    """
    Parses natural language focus into structured config.
    Examples:
      "scenery 7/10"        → {"type": "weight",   "category": "scenery", "weight": 0.7}
      "focus on birthday girl" → {"type": "subject",  "subject": "birthday girl"}
      "7/10 people"         → {"type": "weight",   "category": "people",  "weight": 0.7}
    """
    if not directives:
        return {"type": None}
    
    import re
    focus = {"type": None}
    
    # Weight pattern: "scenery 7/10" or "7/10 scenery"
    match = re.search(r'(\d+)/(\d+)\s*([a-zA-Z]+)|([a-zA-Z]+)\s*(\d+)/(\d+)', directives, re.I)
    if match:
        g = match.groups()
        num, den, cat = (g[0], g[1], g[2]) if g[0] else (g[4], g[5], g[3])
        focus = {"type": "weight", "category": cat.lower(), "weight": int(num)/int(den)}
        return focus
    
    # Subject pattern: "focus on X" or "birthday girl" etc.
    match = re.search(r'focus\s+on\s+(.+)', directives, re.I)
    if match:
        focus = {"type": "subject", "subject": match.group(1).strip()}
    
    return focus


def calculate_alignment_score(seg: dict, directives: str) -> int:
    """
    Calculates how accurately a segment followed the user directives (instructions).
    If no directives are specified, scores based on visual quality, priority, and default parameters.
    """
    if not directives:
        # Fallback when there are no instructions:
        # Map visual_quality (1-10) and priority (1-5, where lower is better) to a 75-98 range.
        vq = int(seg.get("visual_quality", 8) or 8)
        inst = int(seg.get("instagrammable", 8) or 8)
        priority = int(seg.get("priority", 3) or 3)
        priority_bonus = (5 - priority) * 2  # up to 8 points
        base_score = 72 + vq * 1.2 + inst * 0.8 + priority_bonus
        return min(98, max(70, int(base_score)))

    # If there are instructions/directives:
    focus = parse_focus_directive(directives)
    score_val = 70  # starting base score for any valid candidate clip
    
    # Simple word overlap matching from directives
    raw_words = [w.lower().strip(",.!?\"'") for w in directives.split()]
    stop_words = {"the", "a", "an", "on", "in", "of", "and", "or", "to", "for", "with", "at", "by", "from", "focus", "mostly", "scene"}
    query_keywords = [w for w in raw_words if len(w) > 2 and w not in stop_words]
    
    subjects_str = " ".join(seg.get("primary_subjects", [])).lower()
    what_happens = str(seg.get("what_happens") or "").lower()
    reason = str(seg.get("reason") or "").lower()
    loc = str(seg.get("location_tag") or "").lower()
    category = str(seg.get("scene_category") or "").lower()
    
    matches = 0
    for kw in query_keywords:
        if kw in subjects_str:
            matches += 3
        if kw in what_happens:
            matches += 2
        if kw in reason:
            matches += 1
        if kw in loc:
            matches += 2
        if kw in category:
            matches += 2
            
    focus_match = False
    if focus.get("type") == "weight":
        cat = focus["category"]
        if category == cat:
            score_val = 90
            focus_match = True
    elif focus.get("type") == "subject":
        sub_kws = [w.lower().strip(",.!?\"'") for w in focus["subject"].split() if len(w) > 2 and w not in stop_words]
        for kw in sub_kws:
            if kw in subjects_str:
                score_val = max(score_val, 92)
                focus_match = True
            elif kw in what_happens or kw in reason:
                score_val = max(score_val, 85)
                focus_match = True
                
    if matches > 0:
        if focus_match:
            score_val += min(6, matches)
        else:
            score_val = 80 + min(12, matches * 2)
    else:
        if not focus_match:
            # Clip doesn't match the focus directive and has no keyword matches.
            # Give it a lower score (65-75 range) to indicate low relevance to instructions.
            vq = int(seg.get("visual_quality", 5) or 5)
            score_val = 65 + vq
            
    return min(98, max(60, int(score_val)))


def apply_focus_filter(clips: list, focus: dict, total_slots: int) -> list:
    """
    Reorders/filters clip candidates to respect focus directive
    before passing to story sequencer.
    """
    if not focus or not focus.get("type"):
        return clips
    
    if focus["type"] == "weight":
        cat = focus["category"]
        weight = focus["weight"]
        
        target_count = round(total_slots * weight)
        remainder = max(0, total_slots - target_count)
        
        priority = [c for c in clips if str(c.get("scene_category")).lower().strip() == cat]
        others   = [c for c in clips if str(c.get("scene_category")).lower().strip() != cat]
        
        # Cap at available, fill remainder from others
        chosen_priority = priority[:target_count]
        chosen_others   = others[:max(0, total_slots - len(chosen_priority))]
        
        return chosen_priority + chosen_others  # sequencer will reorder narratively
    
    elif focus["type"] == "subject":
        subject_keywords = focus["subject"].lower().split()
        
        def subject_score(clip):
            # Check both primary_subjects and what_happens for semantic matching
            subjects = " ".join(clip.get("primary_subjects", [])).lower()
            what_happens = str(clip.get("what_happens") or "").lower()
            reason = str(clip.get("reason") or "").lower()
            score = sum(kw in subjects for kw in subject_keywords) * 2
            score += sum(kw in what_happens for kw in subject_keywords)
            score += sum(kw in reason for kw in subject_keywords)
            return score
        
        # Sort: matching clips first, non-matching as fillers
        return sorted(clips, key=subject_score, reverse=True)
    
    return clips


# ── Helpers ────────────────────────────────────────────────────────────────────

def auto_recover_segments(parsed: dict) -> dict:
    """Robust fallback: if best_segments is empty/missing but segments is populated, auto-recover them."""
    # Try to get the rotation from the AI, fallback to 0
    rotation = parsed.get("camera_rotation", 0)
    try:
        rotation = int(rotation)
    except (ValueError, TypeError):
        rotation = 0

    if not isinstance(parsed, dict):
        parsed = {}

    best_segs = parsed.get("best_segments")
    if not isinstance(best_segs, list):
        best_segs = []

    # If best_segments is empty, try to recover from other potential list fields
    if not best_segs:
        # Check 'segments'
        if parsed.get("segments") and isinstance(parsed["segments"], list):
            keep_segs = [s for s in parsed["segments"] if s.get("keep") is True]
            source_segs = keep_segs if keep_segs else parsed["segments"]
            import uuid
            for s in source_segs:
                unique_loc = s.get("location_tag") or f"unknown_{uuid.uuid4().hex[:6]}"
                best_segs.append({
                    "start_sec": s.get("start_sec", 0.0),
                    "end_sec": s.get("end_sec", 3.0),
                    "reason": s.get("reason") or s.get("what_happens") or "Auto-recovered highlight segment",
                    "priority": s.get("priority") or 1,
                    "narrative_role": s.get("narrative_role") or s.get("role") or "unknown",
                    "clip_type_applied": s.get("clip_type_applied") or "Auto-recovered segment fallback",
                    "location_tag": unique_loc,
                    "journey_phase": s.get("journey_phase") or "unknown"
                })
        
        # Check 'key_moments' / 'moments'
        elif parsed.get("key_moments") and isinstance(parsed["key_moments"], list):
            import uuid
            for km in parsed["key_moments"]:
                ts = km.get("timestamp_sec", 0.0)
                best_segs.append({
                    "start_sec": ts,
                    "end_sec": ts + 3.0,
                    "reason": km.get("description") or "Auto-recovered from key moment",
                    "priority": 2,
                    "narrative_role": "action",
                    "clip_type_applied": "Key moment fallback",
                    "location_tag": f"unknown_{uuid.uuid4().hex[:6]}",
                    "journey_phase": "unknown"
                })

        # Absolute fallback: if still empty, create one default segment covering 0.0 to 3.0s
        if not best_segs:
            best_segs.append({
                "start_sec": 0.0,
                "end_sec": 3.0,
                "reason": "Fallback: Default segment auto-created due to empty model output.",
                "priority": 3,
                "narrative_role": "unknown",
                "clip_type_applied": "Default fallback",
                "location_tag": "unknown_fallback",
                "journey_phase": "unknown"
            })

    parsed["best_segments"] = best_segs
    for seg in parsed["best_segments"]:
        seg["camera_rotation"] = rotation
    return parsed


def offset_segments(parsed: dict, offset_sec: float) -> dict:
    if offset_sec == 0.0:
        return parsed
    for key in ("segments", "best_segments"):
        for seg in parsed.get(key, []):
            seg["start_sec"] = round(seg.get("start_sec", 0) + offset_sec, 2)
            seg["end_sec"]   = round(seg.get("end_sec",   0) + offset_sec, 2)
    for km in parsed.get("key_moments", []):
        km["timestamp_sec"] = round(km.get("timestamp_sec", 0) + offset_sec, 2)
    return parsed


def merge_chunk_analyses(chunks: list, full_duration: float) -> dict:
    if len(chunks) == 1:
        return chunks[0]
    merged = {
        "video_summary":     " | ".join(c.get("video_summary", "") for c in chunks),
        "detected_scenario": "B",
        "overall_mood":      chunks[0].get("overall_mood",  "unknown"),
        "overall_vibe":      chunks[0].get("overall_vibe",  "unknown"),
        "key_moments": [], "segments": [], "best_segments": [],
    }
    for c in chunks:
        merged["key_moments"]   += c.get("key_moments",   [])
        merged["segments"]      += c.get("segments",      [])
        merged["best_segments"] += c.get("best_segments", [])
    return merged


def merge_adjacent(segs: list, gap: float = 0.5, max_duration: float = 4.0) -> list:
    """
    Merge adjacent best_segments if they are ≤ gap seconds apart,
    but only if the merged result stays under max_duration.
    """
    if not segs:
        return segs
        
    valid_segs = []
    for s in segs:
        if isinstance(s, dict) and "start_sec" in s and "end_sec" in s:
            try:
                s["start_sec"] = float(s["start_sec"])
                s["end_sec"] = float(s["end_sec"])
                valid_segs.append(s)
            except (ValueError, TypeError):
                pass
                
    if not valid_segs:
        return []
        
    segs = sorted(valid_segs, key=lambda s: s["start_sec"])
    merged = [segs[0].copy()]
    for seg in segs[1:]:
        new_end  = max(merged[-1]["end_sec"], seg["end_sec"])
        new_dur  = new_end - merged[-1]["start_sec"]
        gap_dist = seg["start_sec"] - merged[-1]["end_sec"]
        if gap_dist <= gap and new_dur <= max_duration:
            merged[-1]["end_sec"]  = new_end
            merged[-1]["reason"]  = merged[-1].get("reason", "") + " + " + seg.get("reason", "")
            merged[-1]["priority"] = min(merged[-1].get("priority", 999), seg.get("priority", 999))
        else:
            merged.append(seg.copy())
    return merged


def expand_segments(segments: list, min_duration: float = 2.5, video_duration: float = 0.0) -> list:
    """
    Expands the duration of segments to ensure they meet a minimum duration.
    Attempts to expand symmetrically (half before, half after).
    Clamps to the video boundaries.
    """
    for seg in segments:
        try:
            start = float(seg.get("start_sec", 0.0))
            end = float(seg.get("end_sec", 0.0))
            dur = end - start
            
            if dur < min_duration:
                deficit = min_duration - dur
                half = deficit / 2.0
                
                new_start = start - half
                new_end = end + half
                
                # Shift if we hit boundaries
                if new_start < 0.0:
                    new_end += (0.0 - new_start)
                    new_start = 0.0
                    
                if new_end > video_duration:
                    new_start -= (new_end - video_duration)
                    new_end = video_duration
                    
                # Final clamp in case video itself is shorter than min_duration
                new_start = max(0.0, new_start)
                new_end = min(video_duration, new_end)
                
                seg["start_sec"] = new_start
                seg["end_sec"] = new_end
                
        except (ValueError, TypeError):
            pass
            
    return segments


def early_deduplicate_segments(segments: list) -> list:
    """
    Deduplicates segments within the same video.
    Collapses overlapping segments (overlap ratio > 0.3) or segments sharing the same
    location tag early, keeping the one with higher priority (lower priority number).
    """
    if not segments:
        return []
    
    # Sort by priority (lower value = higher priority), default to 999 if not set
    # If priorities are equal, sort by start_sec
    sorted_segs = sorted(
        segments,
        key=lambda s: (int(s.get("priority", 999) or 999), float(s.get("start_sec", 0.0)))
    )
    
    kept = []
    for seg in sorted_segs:
        is_duplicate = False
        seg_start = float(seg.get("start_sec", 0.0))
        seg_end = float(seg.get("end_sec", 0.0))
        seg_loc = seg.get("location_tag", "unknown").lower().strip()
        
        for k in kept:
            k_start = float(k.get("start_sec", 0.0))
            k_end = float(k.get("end_sec", 0.0))
            k_loc = k.get("location_tag", "unknown").lower().strip()
            
            # 1. Overlap Check
            ov = max(0.0, min(seg_end, k_end) - max(seg_start, k_start))
            sh = min(seg_end - seg_start, k_end - k_start)
            overlap_ratio = (ov / sh) if sh > 0.0 else 0.0
            
            # 2. Location Check (only if not 'unknown')
            same_location = (seg_loc != "unknown" and seg_loc == k_loc)
            
            if overlap_ratio > 0.3 or same_location:
                is_duplicate = True
                logging.info(
                    f"  ✂️ [Early Dedup] Collapsed segment [{seg_start:.1f}s–{seg_end:.1f}s, tag={seg_loc}] "
                    f"due to {'overlap (' + str(round(overlap_ratio,2)) + ')' if overlap_ratio > 0.3 else 'matching tag'} "
                    f"with kept segment [{k_start:.1f}s–{k_end:.1f}s, tag={k_loc}]."
                )
                break
                
        if not is_duplicate:
            kept.append(seg)
            
    # Return the kept segments sorted chronologically by start_sec
    return sorted(kept, key=lambda s: float(s.get("start_sec", 0.0)))


# ── Single Video Pipeline (runs in a thread) ───────────────────────────────────

def process_single_video(
    info: dict,
    api_key: str,
    video_quality_map: dict,
    reference_paths: list,
    directives: str = "",
    journey_phase: str = None,
) -> dict:
    # Check cache first thread-safely
    with CACHE_LOCK:
        cache = load_cache()
    
    actual_directives = directives
    if journey_phase:
        phase_directive = f"STORY CONTEXT: This asset belongs to the '{journey_phase}' phase of the story. Please label segments accordingly."
        actual_directives = f"{directives}\n{phase_directive}" if directives else phase_directive

    # Incorporate normalized directives into cache key to avoid cache collisions
    norm_directives = " ".join(actual_directives.lower().split()) if actual_directives else ""
    cache_key = f"{info['path']}_{info['duration_sec']}_{norm_directives}"
    if cache_key in cache:
        cached_val = cache[cache_key]
        # Validate if frame images actually exist on disk
        frames_exist = True
        for frame in cached_val.get("frame_meta", []):
            if not Path(frame.get("path", "")).exists():
                frames_exist = False
                break
        
        if frames_exist:
            logging.info(f"  ✓ [CACHE HIT] Loading cached analysis for {info['path']}")
            return cached_val
        else:
            logging.info(f"  ⚠️  [CACHE HIT] Analysis cached, but timeline frame images are missing on disk for {info['path']}. Regenerating frames...")
            dur          = info["duration_sec"]
            chunk_window = CONFIG["chunk_window_sec"]
            overlap      = CONFIG["chunk_overlap_sec"]
            all_frame_meta = []
            
            if dur <= chunk_window:
                n_frames = pick_frame_count(dur)
                all_frame_meta = extract_representative_frames(
                    info["path"], dur, n_frames, offset_sec=0.0, chunk_label=""
                )
            else:
                starts = []
                t = 0.0
                while t < dur:
                    starts.append(t)
                    t += chunk_window - overlap
                for ci, start in enumerate(starts):
                    window = min(chunk_window, dur - start)
                    if window < 1.0:
                        break
                    label = f"chunk{ci:02d}"
                    n_frames = pick_frame_count(window)
                    fm = extract_representative_frames(
                        info["path"], window, n_frames, offset_sec=start, chunk_label=label
                    )
                    all_frame_meta += fm
            
            # Update frame_meta in cached value and update cache
            cached_val["frame_meta"] = all_frame_meta
            with CACHE_LOCK:
                cache = load_cache()
                cache[cache_key] = cached_val
                save_cache(cache)
            logging.info(f"  ✓ Re-extracted {len(all_frame_meta)} frame(s) successfully for {info['path']}.")
            return cached_val

    dur          = info["duration_sec"]
    chunk_window = CONFIG["chunk_window_sec"]
    overlap      = CONFIG["chunk_overlap_sec"]
    all_frame_meta = []

    logging.info(f"\n▶ {info['path']} ({dur:.1f}s)")

    if dur <= chunk_window:
        fm, parsed     = analyze_window(info, 0.0, dur, api_key, video_quality_map,
                                        reference_paths=reference_paths, directives=actual_directives)
        parsed         = auto_recover_segments(parsed)
        all_frame_meta = fm
        chunk_analyses = [parsed]
    else:
        starts = []
        t = 0.0
        while t < dur:
            starts.append(t)
            t += chunk_window - overlap
        logging.info(f"   Chunked into {len(starts)} windows of ~{chunk_window}s")
        chunk_analyses = []
        for ci, start in enumerate(starts):
            window = min(chunk_window, dur - start)
            if window < 1.0:
                break
            label = f"chunk{ci:02d}"
            logging.info(f"   Chunk {ci+1}/{len(starts)}: [{start:.1f}s–{start+window:.1f}s]")
            fm, parsed = analyze_window(info, start, window, api_key, video_quality_map,
                                        chunk_label=label, reference_paths=reference_paths, directives=actual_directives)
            parsed = auto_recover_segments(parsed)
            parsed = offset_segments(parsed, start)
            all_frame_meta += fm
            chunk_analyses.append(parsed)
        parsed = merge_chunk_analyses(chunk_analyses, dur)

    # Removed early dedup so that all candidate segments make it to the UI library
    parsed["best_segments"] = merge_adjacent(parsed.get("best_segments", []))
    parsed["best_segments"] = expand_segments(parsed["best_segments"], min_duration=2.5, video_duration=dur)
    parsed["best_segments"] = clamp_segments(parsed.get("best_segments", []), dur)
    parsed["segments"]      = clamp_segments(parsed.get("segments",      []), dur)

    # Attach black-frame warning to each best_segment using extracted frames
    for seg in parsed.get("best_segments", []):
        relevant_frames = [
            f for f in all_frame_meta
            if seg["start_sec"] <= f["abs_timestamp"] <= seg["end_sec"]
        ]
        seg["black_frame_warning"] = is_likely_black_clip(relevant_frames)

    is_fb = "[FALLBACK]" in parsed.get("video_summary", "")
    tag   = "⚠️  FALLBACK" if is_fb else "✓ Done"
    logging.info(f"  {tag}: {info['path']}  ({len(parsed.get('best_segments', []))} best segments)")

    res = {
        "video_path":   info["path"],
        "duration_sec": dur,
        "frame_meta":   all_frame_meta,
        "analysis":     parsed,
        "n_chunks":     len(chunk_analyses),
        "creation_time": info.get("creation_time"),
        "location_name": info.get("location_name"),
        "asset_id":      info.get("asset_id"),
    }

    with CACHE_LOCK:
        cache = load_cache()
        cache[cache_key] = res
        save_cache(cache)

    return res


# ── Full Analysis Orchestrator ─────────────────────────────────────────────────

def run_story_context_analysis(video_infos: list, vibe: str, directives: str, tmpdir: str) -> dict:
    """
    Two-step story context pipeline:
      Step 1 — Nemotron (NVIDIA NIM, multiimage): Analyzes each thumbnail visually.
               Returns per-asset descriptions (setting, subjects, activity, tone, trip_phase).
      Step 2 — owl-alpha (OpenRouter, text only): Takes those descriptions and writes
               a rich personal narrative + determines chronological asset_order + phases.
    """
    from app.services.frames_service import extract_thumbnail
    from app.services.prompts_service import build_story_vision_prompt, build_story_narrative_prompt
    from app.services.llm_service import call_openrouter_multiimage, call_openrouter_text

    asset_summaries = []
    MAX_THUMBNAILS = 8

    for idx, info in enumerate(video_infos):
        if idx >= MAX_THUMBNAILS:
            logging.info(f"  ⏭  Skipping story context for asset {idx} (max {MAX_THUMBNAILS} thumbnails).")
            break

        thumb_path = extract_thumbnail(info["path"], tmpdir)
        if thumb_path:
            asset_summaries.append({
                "index": idx,
                "filename": Path(info["path"]).name,
                "thumbnail_path": thumb_path,
                "location_name": info.get("location_name"),
                "creation_time": info.get("creation_time")
            })

    if not asset_summaries:
        logging.warning("  ⚠️  Failed to extract any thumbnails for story context.")
        return None

    num_assets = len(asset_summaries)
    image_paths = [a["thumbnail_path"] for a in asset_summaries]

    # ── STEP 1: Nemotron (NVIDIA NIM) — Visual Analysis ───────────────────────
    vision_model = CONFIG.get("story_vision_model", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning")
    vision_prompt = build_story_vision_prompt(asset_summaries)
    logging.info(f"  🔍 [Story Step 1/2] Sending {num_assets} thumbnails to {vision_model} for visual analysis...")

    asset_descriptions = []
    try:
        import time
        start_t = time.time()
        raw_vision = call_openrouter_multiimage(image_paths, vision_prompt, vision_model)
        dur = time.time() - start_t
        vision_parsed = parse_json_response(raw_vision)
        
        from app.services.logger_service import log_llm_call
        log_llm_call(
            label="story_context_vision", 
            model=vision_model, 
            prompt=vision_prompt, 
            raw_response=raw_vision, 
            parsed=vision_parsed if isinstance(vision_parsed, dict) else None,
            duration_sec=dur
        )
        
        if isinstance(vision_parsed, dict) and "asset_descriptions" in vision_parsed:
            asset_descriptions = vision_parsed["asset_descriptions"]
            logging.info(f"  ✓ [Step 1] Visual analysis complete: {len(asset_descriptions)} asset(s) described.")
        else:
            logging.warning("  ⚠️  [Step 1] Vision model returned unexpected schema. Proceeding with filenames only.")
    except Exception as e:
        logging.error(f"  ✗ [Step 1] Vision analysis failed: {e}. Proceeding with filenames only.")

    # If vision step failed or returned incomplete data, build minimal descriptions from filenames
    if not asset_descriptions or len(asset_descriptions) < num_assets:
        logging.info("  🔄 Filling missing asset descriptions from filenames...")
        described_indices = {d.get("index") for d in asset_descriptions}
        for a in asset_summaries:
            if a["index"] not in described_indices:
                asset_descriptions.append({
                    "index": a["index"],
                    "setting": "unknown",
                    "subjects": "unknown",
                    "activity": "unknown",
                    "time_of_day": "unknown",
                    "emotional_tone": "unknown",
                    "trip_phase": "unknown"
                })
    asset_descriptions = sorted(asset_descriptions, key=lambda d: d.get("index", 0))
    # Enrich descriptions with geocoded location name and creation time
    summaries_by_idx = {a["index"]: a for a in asset_summaries}
    for desc in asset_descriptions:
        idx = desc.get("index")
        if idx in summaries_by_idx:
            desc["location_name"] = summaries_by_idx[idx].get("location_name")
            desc["creation_time"] = summaries_by_idx[idx].get("creation_time")


    # ── STEP 2: owl-alpha (OpenRouter, text only) — Narrative Writing ──────────
    narrative_model = CONFIG.get("story_narrative_model", "openrouter/owl-alpha")
    narrative_prompt = build_story_narrative_prompt(asset_descriptions, vibe, directives, num_assets)
    logging.info(f"  ✍️  [Story Step 2/2] Sending descriptions to {narrative_model} for narrative writing...")

    try:
        import time
        start_t = time.time()
        raw_narrative = call_openrouter_text(
            narrative_prompt,
            model=narrative_model,
            fallbacks=["openai/gpt-4o-mini", "google/gemini-flash-1.5"],
            temperature=0.7,  # slightly creative for narrative writing
        )
        dur = time.time() - start_t
        parsed = parse_json_response(raw_narrative)
        
        from app.services.logger_service import log_llm_call
        log_llm_call(
            label="story_context_narrative", 
            model=narrative_model, 
            prompt=narrative_prompt, 
            raw_response=raw_narrative, 
            parsed=parsed if isinstance(parsed, dict) else None,
            duration_sec=dur
        )
        
        if isinstance(parsed, dict) and "asset_order" in parsed and "story_summary" in parsed:
            summary = parsed.get("story_summary", "")
            logging.info(f"  ✓ [Step 2] Story narrative complete: {summary[:120]}...")
            return parsed
        else:
            logging.warning(f"  ⚠️  [Step 2] Narrative model returned invalid schema: {str(parsed)[:200]}")
            return None
    except Exception as e:
        logging.error(f"  ✗ [Step 2] Narrative writing failed: {e}")
        return None



def run_full_analysis(
    video_infos: list,
    api_key: str,
    video_quality_map: dict,
    reference_paths: list,
    directives: str = "",
    use_uploaded_order: bool = False,
    progress_callback = None,
    story_context: dict = None,
) -> list:
    """
    Run process_single_video for all videos in parallel, then build final
    ordered best_segments list with story ordering.
    """
    def extract_whatsapp_timestamp(filepath: str):
        import re
        from datetime import datetime
        filename = Path(filepath).name
        # Match: WhatsApp Video 2026-06-19 at 16.10.26.mp4 or WhatsApp Image 2026-06-19 at 16.10.26.jpeg
        match = re.search(r'(\d{4}-\d{2}-\d{2})\s+at\s+(\d{2})\.(\d{2})\.(\d{2})', filename)
        if match:
            date_str, hh, mm, ss = match.groups()
            try:
                return datetime.strptime(f"{date_str} {hh}:{mm}:{ss}", "%Y-%m-%d %H:%M:%S")
            except Exception:
                pass
        # Try just matching date
        match_date = re.search(r'(\d{4}-\d{2}-\d{2})', filename)
        if match_date:
            try:
                return datetime.strptime(match_date.group(1), "%Y-%m-%d")
            except Exception:
                pass
        return None

    pipeline_start_time = time.time()

    logging.info(f"\n{'='*60}")
    logging.info(f"Analyzing {len(video_infos)} video(s) in parallel...")
    logging.info(f"{'='*60}")

    max_workers = min(len(video_infos) or 1, CONFIG.get("max_parallel_vision_calls", 3))
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = []
        for idx, info in enumerate(video_infos):
            journey_phase = None
            if story_context and "asset_phases" in story_context:
                journey_phase = story_context["asset_phases"].get(str(idx))
            futures.append(ex.submit(process_single_video, info, api_key, video_quality_map, reference_paths, directives, journey_phase))
        import concurrent.futures
        all_results = []
        for future in concurrent.futures.as_completed(futures):
            all_results.append(future.result())
            if progress_callback:
                progress_callback()

    best_segments = []
    for video_idx, result in enumerate(all_results):
        # Find the original index of this video in the input video_infos list to ensure
        # that video_idx matches the media_assets sequence index (and does not depend on
        # the arbitrary order in which parallel threads complete).
        orig_video_idx = next(
            (i for i, info in enumerate(video_infos) if info["path"] == result["video_path"]),
            video_idx
        )
        segs = sorted(result["analysis"].get("best_segments", []),
                      key=lambda s: float(s.get("start_sec", 0)))
        for seg in segs:
            # Programmatic quality guard: Reject segments that are too blurry to prevent AI hallucinations
            q_data = video_quality_map.get(result["video_path"], {})
            samples = q_data.get("samples", [])
            is_blurry_segment = False
            if samples and not result.get("is_image", False):
                seg_samples = [s for s in samples if float(seg.get("start_sec", 0)) <= s["t"] <= float(seg.get("end_sec", 0))]
                if seg_samples:
                    avg_blur = sum(s.get("blur_raw", 1000.0) for s in seg_samples) / len(seg_samples)
                    if avg_blur < 45.0:
                        logging.info(f"  ⏭  Programmatically rejected segment [{seg.get('start_sec')}s–{seg.get('end_sec')}s] "
                                     f"from {Path(result['video_path']).name} due to excessive blur (avg raw blur: {avg_blur:.2f} < 45.0)")
                        is_blurry_segment = True
            
            if is_blurry_segment:
                continue

            constructed_seg = {
                "video_path":         result["video_path"],
                "video_idx":          orig_video_idx,
                "video_duration_sec": result["duration_sec"],
                "video_summary":      result["analysis"].get("video_summary",  ""),
                "overall_mood":       result["analysis"].get("overall_mood",   ""),
                "overall_vibe":       result["analysis"].get("overall_vibe",   ""),
                "editor_reasoning":   result["analysis"].get("editor_reasoning", ""),
                "start_sec":          seg.get("start_sec"),
                "end_sec":            seg.get("end_sec"),
                "reason":             seg.get("reason"),
                "priority":           seg.get("priority"),
                "camera_rotation":    seg.get("camera_rotation", 0),
                "narrative_role":     seg.get("narrative_role",         "unknown"),
                "scenario_rule":      seg.get("scenario_rule_applied",  ""),
                "location_tag":       seg.get("location_tag",           "unknown"),
                "journey_phase":      seg.get("journey_phase",          "unknown"),
                "time_of_day":        seg.get("time_of_day",            "unknown"),
                "black_frame_warning": seg.get("black_frame_warning",   False),
                "is_image":           result.get("is_image", False),
                "scene_category":     seg.get("scene_category", "mixed"),
                "primary_subjects":   seg.get("primary_subjects", []),
                "what_happens":       seg.get("what_happens", ""),
                "mood":               seg.get("mood", ""),
                "creation_time":      result.get("creation_time"),
                "location_name":      result.get("location_name"),
                "asset_id":           result.get("asset_id"),
            }
            constructed_seg["ai_score"] = calculate_alignment_score(constructed_seg, directives)
            best_segments.append(constructed_seg)

    # ── Same-video dedup: allow multiple highlights from the same long video if different locations ──
    # If the clips from the same source video do not overlap, have different location tags,
    # and are separated by a sufficient time gap (at least 3.0s), we allow keeping them.
    # We allow up to 3 clips for long videos (> 30s) and up to 2 clips for shorter videos.
    def deduplicate_by_source_video(segments: list) -> list:
        from collections import defaultdict
        by_video = defaultdict(list)
        for seg in segments:
            by_video[seg["video_path"]].append(seg)
        kept = []
        for path, clips in by_video.items():
            if len(clips) <= 1:
                kept.extend(clips)
                continue
            
            # Sort by priority (lower = better)
            sorted_clips = sorted(clips, key=lambda s: int(s.get("priority", 999) or 999))
            
            # Dynamically determine the maximum clips allowed for this video based on duration
            first_clip = sorted_clips[0]
            video_dur = float(first_clip.get("video_duration_sec", 30.0))
            max_clips = 3 if video_dur > 30.0 else 2
            
            video_kept = [first_clip]
            for clip in sorted_clips[1:]:
                is_ok = True
                for k in video_kept:
                    # check overlap
                    ov = max(0, min(clip["end_sec"], k["end_sec"]) - max(clip["start_sec"], k["start_sec"]))
                    sh = min(clip["end_sec"] - clip["start_sec"], k["end_sec"] - k["start_sec"])
                    overlap_ratio = (ov / sh) if sh > 0 else 0
                    
                    # check time gap (distance between segments)
                    clip_start, clip_end = float(clip["start_sec"]), float(clip["end_sec"])
                    k_start, k_end = float(k["start_sec"]), float(k["end_sec"])
                    gap = max(clip_start, k_start) - min(clip_end, k_end)
                    
                    # If they overlap or have a gap smaller than 2.0s, reject
                    if overlap_ratio > 0.3 or gap < 2.0:
                        is_ok = False
                        break

                    # Check semantic/visual similarity to detect near-identical frames/shots
                    clip_loc = clip.get("location_tag", "unknown").lower().strip()
                    k_loc = k.get("location_tag", "unknown").lower().strip()
                    clip_cat = clip.get("scene_category", "mixed").lower().strip()
                    k_cat = k.get("scene_category", "mixed").lower().strip()
                    
                    if clip_loc != "unknown" and clip_loc == k_loc:
                        # Stricter deduplication: If it's the exact same video AND the AI 
                        # gave it the exact same location tag, check if their primary subjects 
                        # are different enough to warrant keeping both.
                        subs_clip = {s.lower().strip() for s in clip.get("primary_subjects", [])}
                        subs_k = {s.lower().strip() for s in k.get("primary_subjects", [])}
                        if subs_clip and subs_k:
                            intersection = subs_clip & subs_k
                            union = subs_clip | subs_k
                            jaccard = len(intersection) / len(union) if union else 0.0
                            # If they share less than 60% of their subjects, keep both
                            if jaccard < 0.6:
                                continue
                        is_ok = False
                        break
                        
                    if clip_cat != "unknown" and clip_cat == k_cat:
                        # Also check description / reason overlap if categories match but location tags differ
                        desc_clip = (clip.get("what_happens", "") or clip.get("reason", "")).lower()
                        desc_k = (k.get("what_happens", "") or k.get("reason", "")).lower()
                        stop_words = {"the", "a", "an", "on", "in", "of", "and", "or", "to", "for", "with", "at", "by", "from"}
                        words_clip = {w.strip(",.!?\"'") for w in desc_clip.split() if len(w) > 2 and w not in stop_words}
                        words_k = {w.strip(",.!?\"'") for w in desc_k.split() if len(w) > 2 and w not in stop_words}
                        
                        desc_overlap = 0.0
                        if words_clip and words_k:
                            desc_overlap = len(words_clip & words_k) / min(len(words_clip), len(words_k))
                            
                        if desc_overlap >= 0.3:
                            is_ok = False
                            break
                if is_ok and len(video_kept) < max_clips:
                    video_kept.append(clip)
            kept.extend(video_kept)
        return kept

    # ── Deduplicate by location tag ─────────────────────────────────────────
    # If different source videos share the same location_tag, they might be showing completely different angles, times of day, or subject interactions (e.g. sunset silhouette vs. regular walk).
    # Therefore, we group by location tag but keep the best clip per unique source video!
    def deduplicate_by_location(segments: list) -> list:
        # We don't want to limit to a single best clip per video path here,
        # as deduplicate_by_source_video already handles filtering within the same video
        # while respecting time gaps, overlaps, and priority.
        return segments

    # ── Overlap Deduplication Helper ─────────────────────────────────────────
    def overlaps(a, b):
        if a["video_path"] != b["video_path"]:
            return False
        ov = max(0, min(a["end_sec"], b["end_sec"]) - max(a["start_sec"], b["start_sec"]))
        sh = min(a["end_sec"] - a["start_sec"], b["end_sec"] - b["start_sec"])
        return sh > 0 and (ov / sh) > 0.5

    # ── Identify selected segments via copy-filtering ─────────────────────────
    survived = list(best_segments)
    survived = deduplicate_by_source_video(survived)
    survived = deduplicate_by_location(survived)

    deduped = []
    for seg in survived:
        dup = False
        for existing in deduped:
            if overlaps(seg, existing):
                if (seg.get("priority") or 999) < (existing.get("priority") or 999):
                    deduped.remove(existing)
                    break
                else:
                    dup = True
                    break
        if not dup:
            deduped.append(seg)
    survived = deduped

    # ── Focus Filtering & Re-ranking ──
    focus = parse_focus_directive(directives)
    if focus.get("type"):
        logging.info(f"  🎯 Focus Weighting / Subject Focus active: {focus}")
        
    def get_focus_sort_key(seg):
        if not focus or not focus.get("type"):
            return 0
        if focus["type"] == "weight":
            cat = focus["category"]
            is_match = str(seg.get("scene_category")).lower().strip() == cat
            return 0 if is_match else 1
        elif focus["type"] == "subject":
            subject_keywords = focus["subject"].lower().split()
            subjects = " ".join(seg.get("primary_subjects", [])).lower()
            what_happens = str(seg.get("what_happens") or "").lower()
            reason = str(seg.get("reason") or "").lower()
            score = sum(kw in subjects for kw in subject_keywords) * 2
            score += sum(kw in what_happens for kw in subject_keywords)
            score += sum(kw in reason for kw in subject_keywords)
            return -score
        return 0

    # ── Duration budget ─────────────────────────────────────────────────────
    MAX_REEL_SEC = CONFIG.get("max_reel_sec", 60)
    total = 0.0
    kept  = []
    for seg in sorted(survived, key=lambda s: (
                        get_focus_sort_key(s),
                        int(s.get("priority", 999) or 999),
                        float(s.get("end_sec", 0)) - float(s.get("start_sec", 0)))):
        dur = float(seg["end_sec"]) - float(seg["start_sec"])
        if total + dur <= MAX_REEL_SEC or not kept:
            kept.append(seg)
            total += dur
        else:
            logging.info(f"  ⏭  Dropped (budget): {seg['video_path']} {seg['start_sec']}s–{seg['end_sec']}s")
    survived = kept
    logging.info(f"Duration budget: {total:.1f}s reel from {len(survived)} survived clips out of {len(best_segments)} total")

    # Mark survived items as is_used = True (others remain False)
    survived_keys = {(s["video_path"], s["start_sec"], s["end_sec"]) for s in survived}
    for seg in best_segments:
        if (seg["video_path"], seg["start_sec"], seg["end_sec"]) in survived_keys:
            seg["is_used"] = True
        else:
            seg["is_used"] = False

    # ── Temporal Pre-sorting or Uploaded Order Sorting ────────────────────────
    def sort_by_timestamp_and_idx(segments):
        def get_sort_key(s):
            ts = extract_whatsapp_timestamp(s["video_path"])
            if ts:
                return (ts, int(s.get("video_idx", 0)), float(s.get("start_sec", 0.0)))
            else:
                from datetime import datetime
                TIME_ORDER = {
                    "dawn": 0, "morning": 1, "afternoon": 2, "day": 2, "midday": 2,
                    "golden_hour": 3, "sunset": 3, "dusk": 4, "evening": 4, "night": 5, "unknown": 6
                }
                fallback_time_val = TIME_ORDER.get(s.get("time_of_day", "unknown"), 6)
                dummy_ts = datetime.combine(datetime.min.date(), datetime.min.time().replace(hour=fallback_time_val))
                return (dummy_ts, int(s.get("video_idx", 0)), float(s.get("start_sec", 0.0)))
        return sorted(segments, key=get_sort_key)

    asset_order = []
    if story_context and "asset_order" in story_context:
        asset_order = story_context["asset_order"]
        
    if asset_order:
        logging.info(f"Sorting clips by LLM-defined asset_order: {asset_order}")
        path_to_idx = {str(res["video_path"]): idx for idx, res in enumerate(all_results)}
        def get_story_sort_key(seg):
            v_path = str(seg["video_path"])
            src_idx = path_to_idx.get(v_path, 999)
            try:
                order_pos = asset_order.index(src_idx)
            except ValueError:
                order_pos = 999
            return (order_pos, float(seg.get("start_sec", 0.0)))
        survived = sorted(survived, key=get_story_sort_key)
    elif use_uploaded_order:
        logging.info("  📂 Sorting clips strictly by uploaded file order...")
        survived = sorted(
            survived,
            key=lambda s: (int(s.get("video_idx", 0)), float(s.get("start_sec", 0.0)))
        )
    else:
        logging.info("  📂 Sorting clips chronologically by filename timestamps...")
        survived = sort_by_timestamp_and_idx(survived)

    # ── Story ordering (run only on survived clips) ─────────────────────────
    story_order = list(range(len(survived)))
    story_roles = ["clip"] * len(survived)
    story_reasoning = ""
    story_transitions = []
    story_transition_durations = []

    # Run LLM story ordering unless the user explicitly requested uploaded order
    if not use_uploaded_order:
        
        # Determine landscape vs portrait for each clip to help the LLM prioritize vertical clips
        for seg in survived:
            try:
                is_img = seg.get("is_image", False) or Path(seg["video_path"]).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
                import cv2
                if is_img:
                    frame = cv2.imread(str(seg["video_path"]))
                    if frame is not None:
                        eff_h, eff_w = frame.shape[:2]
                    else:
                        eff_w, eff_h = 1080, 1920
                else:
                    cap = cv2.VideoCapture(str(seg["video_path"]))
                    eff_w = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
                    eff_h = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
                    cap.release()
                
                input_aspect = eff_w / eff_h if eff_h else 1
                seg["is_landscape"] = input_aspect > 1.0
            except Exception:
                seg["is_landscape"] = False

        story_prompt = build_story_order_prompt(survived, all_results, directives, focus, story_context)
        t0 = time.time()
        raw_order = None
        story_model = CONFIG.get("story_order_model", CONFIG["model"])
        try:
            raw_order    = call_openrouter_text(
                story_prompt,
                story_model,
                fallbacks=[CONFIG.get("story_order_fallback")] if "story_order_fallback" in CONFIG else None
            )
            duration = time.time() - t0
            parsed_order = parse_json_response(raw_order)
            log_story_order_call(
                model=story_model,
                prompt=story_prompt,
                raw_response=raw_order or "",
                parsed=parsed_order,
                parse_error=None,
                duration_sec=duration,
            )
            order = parsed_order.get("order", [])
            roles = parsed_order.get("roles", [])
            llm_transitions = parsed_order.get("transitions", [])
            llm_durations = parsed_order.get("transition_durations", [])
            
            removed_clips_data = parsed_order.get("removed_clips", [])
            explicitly_removed = set()
            for r in removed_clips_data:
                idx = r.get("clip")
                if isinstance(idx, int):
                    explicitly_removed.add(idx)

            # ── Lenient validation: accept valid subset, append missing indices ──
            n = len(survived)
            # Filter to only valid, in-range, distinct indices
            seen = set()
            clean_order = []
            clean_roles = []
            for pos, idx_or_group in enumerate(order):
                if isinstance(idx_or_group, list):
                    group = []
                    for idx in idx_or_group:
                        if isinstance(idx, int) and 0 <= idx < n and idx not in seen:
                            group.append(idx)
                            seen.add(idx)
                        else:
                            logging.info(f"  ⚠️  Story order: dropping invalid/duplicate index {idx} in group")
                    if group:
                        clean_order.append(group if len(group) > 1 else group[0])
                        clean_roles.append(roles[pos] if pos < len(roles) else "build")
                elif isinstance(idx_or_group, int) and 0 <= idx_or_group < n and idx_or_group not in seen:
                    clean_order.append(idx_or_group)
                    clean_roles.append(roles[pos] if pos < len(roles) else "build")
                    seen.add(idx_or_group)
                else:
                    logging.info(f"  ⚠️  Story order: dropping invalid/duplicate index {idx_or_group}")

            # Append any clips the LLM forgot to include (that weren't explicitly removed)
            missing = [i for i in range(n) if i not in seen and i not in explicitly_removed]
            if missing:
                logging.info(f"  ⚠️  Story order: LLM missed indices {missing} — appending them at end")
                for idx in missing:
                    clean_order.append(idx)
                    clean_roles.append("build")

            if clean_order:
                story_order = clean_order
                story_roles = clean_roles
                story_reasoning = parsed_order.get('reasoning', '')
                story_transitions = llm_transitions
                story_transition_durations = llm_durations
                logging.info(f"Story order: {story_order}")
                logging.info(f"Roles:       {story_roles}")
                logging.info(f"Reasoning:   {story_reasoning}")
                if story_transitions:
                    logging.info(f"LLM Transitions: {story_transitions}")
            else:
                logging.info(f"Story order: LLM returned no usable indices — keeping original.")
        except Exception as e:
            duration = time.time() - t0
            log_story_order_call(
                model=story_model,
                prompt=story_prompt,
                raw_response=raw_order or "",
                parsed=None,
                parse_error=str(e),
                duration_sec=duration,
            )
            logging.info(f"Story ordering failed ({e}), keeping original order.")

    # ── POST-PROCESS: Force all solo landscape clips into split-screen grids ──
    def enforce_landscape_grids(order: list, survived: list) -> list:
        """
        STEP 1: Fully flatten the entire LLM order — including breaking apart any
        existing grids the LLM formed. This catches cases where the LLM cheated by
        jamming portrait clips into a grid just to satisfy the landscape rule.

        STEP 2: Walk the flat list in original sequence order. Split clips into
        landscape vs portrait buckets, preserving their relative positions.

        STEP 3: Form pure landscape-only grids (3 at a time). If fewer than 3
        landscape clips exist, they fall back to playing individually.

        STEP 4: Interleave the grids and portrait clips back together, placing
        each grid at the position of its first constituent clip.
        """
        # ── STEP 1: Flatten everything into (original_pos, clip_idx) pairs ──
        flat = []  # list of (original_position_in_order, clip_index)
        for pos, item in enumerate(order):
            if isinstance(item, list):
                # Existing grid — break it apart and treat each clip individually
                for sub_idx in item:
                    flat.append((pos, sub_idx))
            else:
                flat.append((pos, item))

        # ── STEP 2: Separate landscape vs portrait clips ──
        landscape_clips = []   # (original_pos, clip_idx) for landscape clips
        portrait_clips  = []   # (original_pos, clip_idx) for portrait clips

        for (pos, idx) in flat:
            seg = survived[idx]
            if seg.get("is_landscape", False):
                landscape_clips.append((pos, idx))
            else:
                portrait_clips.append((pos, idx))

        n_landscape = len(landscape_clips)

        if n_landscape < 3:
            # Not enough landscape clips for even one grid — return original order untouched
            logging.info(
                f"  ℹ️  [enforce_landscape_grids] Only {n_landscape} landscape clip(s) total "
                f"(including inside LLM grids). Not enough for a pure grid. Restoring individual playback."
            )
            # Reconstruct order as all-individual (break up any bad mixed grids)
            return [idx for (_, idx) in flat]

        # ── STEP 3: Form pure landscape-only grids ──
        n_full_grids = n_landscape // 3
        n_leftover   = n_landscape % 3

        logging.info(
            f"  🔲 [enforce_landscape_grids] {n_landscape} landscape clip(s) found. "
            f"Forming {n_full_grids} pure landscape grid(s), {n_leftover} individual leftover(s)."
        )

        landscape_indices = [idx for (_, idx) in landscape_clips]
        grids = [landscape_indices[g * 3 : g * 3 + 3] for g in range(n_full_grids)]
        leftover_landscape = landscape_indices[n_full_grids * 3:]

        # ── STEP 4: Rebuild the final order ──
        # Strategy: walk through `flat` in order. When we hit the first clip of
        # a landscape group, emit the grid. Skip subsequent clips in that group.
        # Portrait clips get emitted as-is. Leftover landscape clips also as-is.

        grid_inserted_at = set()   # which grid numbers have been emitted
        landscape_rank_map = {idx: rank for rank, (_, idx) in enumerate(landscape_clips)}

        new_order = []
        for (pos, idx) in flat:
            seg = survived[idx]
            if seg.get("is_landscape", False):
                rank = landscape_rank_map[idx]
                group_num = rank // 3

                if group_num >= n_full_grids:
                    # Leftover landscape — play individually
                    new_order.append(idx)
                elif group_num not in grid_inserted_at:
                    # First clip of this group → emit the whole grid
                    new_order.append(grids[group_num])
                    grid_inserted_at.add(group_num)
                # else: 2nd or 3rd clip of an already-emitted grid → skip
            else:
                new_order.append(idx)

        return new_order

    # ── Tag each clip with is_landscape using ffprobe (rotation-aware) ──────────
    # OpenCV ignores rotation metadata embedded by smartphones, so it would
    # report a landscape video saved as portrait (with rotation=90) as portrait.
    # ffprobe reads the actual display dimensions correctly.
    def get_effective_dimensions(video_path: str):
        """Use ffprobe to get the display width/height (respecting rotation tag)."""
        import json as _json
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,codec_tag_string:stream_tags=rotate:stream_side_data_list",
                "-of", "json",
                str(video_path)
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=10)
            data = _json.loads(res.stdout)
            stream = data.get("streams", [{}])[0]
            w = stream.get("width", 0)
            h = stream.get("height", 0)

            # Check rotation tag: 90 or 270 means width/height are swapped visually
            rotation = 0
            tags = stream.get("tags", {})
            if "rotate" in tags:
                rotation = abs(int(tags["rotate"]))
            # Also check side_data_list for modern rotation info
            for sd in stream.get("side_data_list", []):
                if "rotation" in sd:
                    rotation = abs(int(sd["rotation"]))
                    break

            if rotation in (90, 270):
                # Physically swapped — the displayed width and height are inverted
                return h, w
            return w, h
        except Exception:
            return 0, 0

    for seg in survived:
        try:
            is_img = seg.get("is_image", False) or Path(seg["video_path"]).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
            if is_img:
                import cv2 as _cv2
                frame = _cv2.imread(str(seg["video_path"]))
                if frame is not None:
                    eff_h, eff_w = frame.shape[:2]
                else:
                    eff_w, eff_h = 1080, 1920
            else:
                eff_w, eff_h = get_effective_dimensions(seg["video_path"])
                if eff_w == 0:  # ffprobe failed — fall back to OpenCV
                    import cv2 as _cv2
                    cap = _cv2.VideoCapture(str(seg["video_path"]))
                    eff_w = int(cap.get(_cv2.CAP_PROP_FRAME_WIDTH))
                    eff_h = int(cap.get(_cv2.CAP_PROP_FRAME_HEIGHT))
                    cap.release()

            aspect = eff_w / eff_h if eff_h else 1.0
            seg["is_landscape"] = aspect > 1.0
            logging.info(
                f"  📐 [landscape_tag] {Path(seg['video_path']).name}: "
                f"effective={eff_w}x{eff_h} → is_landscape={seg['is_landscape']}"
            )
        except Exception as _e:
            seg["is_landscape"] = False
            logging.warning(f"  ⚠️  [landscape_tag] Failed to detect aspect for {seg.get('video_path')}: {_e}")

    # Only enforce grids when the LLM ran (not when using uploaded order)
    if not use_uploaded_order and len(survived) >= 2:
        story_order = enforce_landscape_grids(story_order, survived)
        logging.info(f"Story order (after grid enforcement): {story_order}")

    # ── Apply story ordering to survived clips ───────────────────────────────
    ordered_survived = []

    actually_used_keys = set()
    for position, idx_or_group in enumerate(story_order):
        
        def apply_pacing(seg_obj, role="build"):
            loc_lower = str(seg_obj.get("location_tag", "")).lower()
            desc_lower = str(seg_obj.get("what_happens", "")).lower()
            subjs_lower = " ".join([str(s).lower() for s in seg_obj.get("primary_subjects", [])])
            combined_text = f"{loc_lower} {desc_lower} {subjs_lower}"

            start = float(seg_obj["start_sec"])
            end = float(seg_obj["end_sec"])
            duration = end - start
            video_dur = float(seg_obj.get("video_duration_sec", 999.0))

            is_action = any(kw in combined_text for kw in ["pool", "swim", "water", "action", "ping", "pong", "tennis", "play", "jump", "active", "splash", "game"])
            is_slow = any(kw in combined_text for kw in ["sunset", "candle", "temple", "serene", "calm", "reflection", "slow", "beauty", "scenery", "night"])

            if role == "payoff":
                target_dur = max(4.5, min(6.0, duration))
                target_end = min(video_dur, start + target_dur)
                seg_obj["end_sec"] = round(target_end, 2)
            elif is_action:
                target_dur = min(3.0, max(2.0, duration))
                target_end = min(video_dur, start + target_dur)
                seg_obj["end_sec"] = round(target_end, 2)
            elif is_slow:
                target_dur = max(4.0, min(5.0, duration))
                target_end = min(video_dur, start + target_dur)
                seg_obj["end_sec"] = round(target_end, 2)
            else:
                # Allow normal clips to run up to 4.5s for a longer, more complete reel duration
                target_dur = max(3.5, min(4.5, duration))
                target_end = min(video_dur, start + target_dur)
                seg_obj["end_sec"] = round(target_end, 2)

            if seg_obj["end_sec"] <= seg_obj["start_sec"] + 0.1:
                seg_obj["end_sec"] = round(seg_obj["start_sec"] + 0.1, 2)
            return seg_obj
        
        # Determine global role and transition for this position
        role = story_roles[position] if position < len(story_roles) else "build"
        if position == 0: role = "hook"
        elif position == len(story_order) - 1: role = "payoff"
        elif role in ("hook", "payoff"): role = "build"
        
        next_trans = None
        next_trans_dur = None
        if position < len(story_order) - 1:
            if story_transitions and position < len(story_transitions):
                next_trans = story_transitions[position]
            if story_transition_durations and position < len(story_transition_durations):
                try:
                    next_trans_dur = float(story_transition_durations[position])
                except (ValueError, TypeError): pass

        if isinstance(idx_or_group, list):
            # Process split screen group
            grouped_segs = []
            for sub_idx in idx_or_group:
                sub_seg = survived[sub_idx].copy()
                sub_seg["is_used"] = True
                sub_seg = apply_pacing(sub_seg, role)
                grouped_segs.append(sub_seg)
                actually_used_keys.add((sub_seg["video_path"], sub_seg["start_sec"], sub_seg["end_sec"]))
            
            group_obj = {
                "is_split_screen": True,
                "is_used": True,
                "story_position": position,
                "story_role": role,
                "clips": grouped_segs
            }
            if next_trans: group_obj["next_transition"] = next_trans
            if next_trans_dur is not None: group_obj["next_transition_duration"] = next_trans_dur
            if position == 0 and story_reasoning: group_obj["global_story_reasoning"] = story_reasoning
            
            ordered_survived.append(group_obj)
        else:
            seg = survived[idx_or_group].copy()
            seg["is_used"] = True
            seg = apply_pacing(seg, role)
            seg["story_position"] = position
            seg["story_role"] = role
            
            if next_trans: seg["next_transition"] = next_trans
            if next_trans_dur is not None: seg["next_transition_duration"] = next_trans_dur
            if position == 0 and story_reasoning: seg["global_story_reasoning"] = story_reasoning
                
            ordered_survived.append(seg)
            actually_used_keys.add((seg["video_path"], seg["start_sec"], seg["end_sec"]))

    def enforce_no_consecutive_same_source(ordered_segs):
        """Only prevent clips from the exact same source video file appearing back-to-back."""
        segs = list(ordered_segs)
        changed = True
        passes = 0
        while changed and passes < 3:
            changed = False
            passes += 1
            for i in range(1, len(segs)):
                prev_src = segs[i-1].get("video_path", "")
                curr_src = segs[i].get("video_path", "")
                if prev_src == curr_src:
                    # Find a non-adjacent swap partner
                    for j in range(i + 1, len(segs)):
                        if segs[j].get("video_path", "") != prev_src:
                            segs[i], segs[j] = segs[j], segs[i]
                            changed = True
                            break
        return segs

    # Ensure no consecutive same-source clips to prevent duplicate/jarring jump cuts
    filtered_ordered = []
    for seg in ordered_survived:
        is_split = seg.get("is_split_screen", False)
        if not is_split and filtered_ordered and not filtered_ordered[-1].get("is_split_screen", False):
            if filtered_ordered[-1]["video_path"] == seg["video_path"]:
                logging.info(f"  ⏭  Dropping back-to-back same-source clip from {Path(seg['video_path']).name} ({seg['start_sec']}s-{seg['end_sec']}s) to prevent duplicate look")
                actually_used_keys.discard((seg["video_path"], seg["start_sec"], seg["end_sec"]))
                continue
        filtered_ordered.append(seg)
    ordered_survived = filtered_ordered

    for position, seg in enumerate(ordered_survived):
        seg["story_position"] = position



    # ── Append unused/duplicate clips at the end ─────────────────────────────
    # This includes clips rejected by hard deduplication AND clips rejected by the Story LLM
    unused = []
    for seg in best_segments:
        if (seg["video_path"], seg["start_sec"], seg["end_sec"]) not in actually_used_keys:
            seg_copy = seg.copy()
            seg_copy["is_used"]        = False
            seg_copy["story_position"] = len(ordered_survived) + len(unused)
            seg_copy["story_role"]     = "clip"
            unused.append(seg_copy)

    ordered = ordered_survived + unused

    write_run_summary(
        all_results=all_results,
        final_segments=ordered,
        story_order=story_order,
        total_duration_sec=time.time() - pipeline_start_time,
    )

    return ordered, all_results


# ── Single Manual Segment Analyzer ────────────────────────────────────────────

def build_single_segment_prompt(video_path: str, start_sec: float, end_sec: float, duration: float) -> str:
    return f"""You are a precise video analyst for a short-form reel editor.

CRITICAL INSTRUCTION FOR REASONING AND THINKING:
Keep your internal thinking process (the reasoning path before outputting JSON) extremely short, concise, and direct (maximum 3-4 sentences total). Do not write long explanations or redundant descriptions. Summarize your thoughts immediately and output the final JSON object.

Analyze this specific video segment from {start_sec}s to {end_sec}s (duration: {duration:.2f}s).

The frames provided are in chronological order from within this segment.

Analyze the visual content of this segment and return ONLY a valid JSON object with the following fields:
{{
  "journey_phase": "string — one of: approach | arrival | exterior | interior | detail | departure | cruise | unknown",
  "location_tag": "string — short canonical name for this physical location, e.g. 'flight_screen', 'airplane_window', 'airport_view'",
  "narrative_role": "string — setup / action / climax / reaction / payoff / establishing_shot",
  "overall_mood": "string — e.g. 'Serene, aspirational'",
  "overall_vibe": "string — e.g. 'Travel, sunset flight'",
  "reason": "string — a compelling 1-sentence description of why this specific moment is visually strong or interesting",
  "scenario_rule": "string — scenario description, e.g. 'Scenario B: Hand reaches for airplane window'",
  "video_summary": "string — a 1-2 sentence descriptive summary of exactly what is happening in this segment"
}}

Rules:
- Do not include markdown, code fences, or any text outside the JSON object.
- Keep the response extremely precise and accurate to the actual frames shown.
"""

def analyze_single_segment(video_path: str, start_sec: float, end_sec: float, api_key: str) -> dict:
    """
    Directly extracts frames for a single timeline clip window,
    sends a focused vision request to the LLM, and returns the analyzed fields.
    """
    duration = max(0.1, end_sec - start_sec)
    
    # Extract 3 representative frames for this precise window
    frame_meta = extract_representative_frames(
        video_path, duration, frames_per_video=3,
        offset_sec=start_sec, chunk_label="manual_analysis"
    )
    
    if not frame_meta:
        raise ValueError("Could not extract frames for the selected segment.")
        
    payload_images = [f["path"] for f in frame_meta]
    prompt = build_single_segment_prompt(video_path, start_sec, end_sec, duration)
    
    raw = call_openrouter_multiimage(payload_images, prompt, CONFIG["model"])
    parsed = parse_json_response(raw)
    if not isinstance(parsed, dict):
        raise ValueError("Parsed JSON is not a dictionary")
    if "journey_phase" not in parsed or "location_tag" not in parsed:
        raise ValueError("Parsed JSON is missing 'journey_phase' or 'location_tag' key")
    
    # Attach safety fields
    parsed["black_frame_warning"] = is_likely_black_clip(frame_meta)
    return parsed

import tempfile
import os
import shutil
import logging
from sqlalchemy.future import select
from app.core.celery_app import celery_app
from app.core.database import AsyncSessionLocal
from app.models.domain import AnalysisJob, AnalyzedClip, JobStatus
from app.services.storage_service import storage_service

@celery_app.task(bind=True)
def analyze_video_project(self, project_id: str, job_id: str, media_assets: list, directives: str = "", vibe: str = "cinematic", music_config: dict = None):
    import uuid
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from app.core.config import settings

    job_uuid = uuid.UUID(job_id)
    project_uuid = uuid.UUID(project_id)

    # Create engine and loop INSIDE the task to prevent any sharing across forks or loops
    task_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, echo=False)
    TaskSessionLocal = async_sessionmaker(task_engine, expire_on_commit=False)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _update_progress(p: int, status: JobStatus = None, error: str = None):
        async with TaskSessionLocal() as db:
            result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == job_uuid))
            job = result.scalar_one_or_none()
            if job:
                job.progress = p
                if status:
                    job.status = status
                if error:
                    job.error_message = error
                await db.commit()

    def update_progress(p: int, status: JobStatus = None, error: str = None):
        loop.run_until_complete(_update_progress(p, status, error))

    try:
        update_progress(5, JobStatus.RUNNING)
        from app.services.logger_service import init_run_log_dir
        init_run_log_dir(project_id, job_id)
        logging.info(f"  🎬 [Pipeline] Starting analysis | vibe={vibe!r} | directives={directives!r}")

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            import requests
            import threading
            video_paths = []
            
            update_progress(10)
            from app.services.storage_service import storage_service
            for idx, asset in enumerate(media_assets):
                ext = asset.get('file_name', '').split('.')[-1]
                if not ext:
                    ext = 'mp4'
                local_path = os.path.join(tmpdir, f"asset_{idx}.{ext}")
                presigned = storage_service.generate_presigned_url(asset["storage_path"])
                r = requests.get(presigned)
                
                if r.status_code != 200:
                    logging.error(f"  ❌ Failed to download {asset.get('file_name', 'unknown')} (status={r.status_code}) from MinIO. Is the file missing?")
                    continue
                    
                with open(local_path, "wb") as f:
                    f.write(r.content)
                
                # DEBUG
                file_size = os.path.getsize(local_path)
                logging.info(f"  📥 Downloaded {asset.get('file_name', 'unknown')} → {local_path} ({file_size} bytes, status={r.status_code})")
                
                video_paths.append(local_path)
                
            video_infos = []
            for idx, vp in enumerate(video_paths):
                info = get_video_info(vp)
                if info:
                    info["asset_id"] = str(media_assets[idx].get("id"))
                    info["filename"] = media_assets[idx].get("file_name") or media_assets[idx].get("filename")
                    video_infos.append(info)

            # Sort video_infos chronologically by creation_time to ensure chronological story order mapping
            def get_chrono_key(x):
                ct = x.get("creation_time")
                if not ct:
                    return (1, "")
                # Normalize time string to make it comparable
                t = str(ct).strip().replace(":", "-").replace("T", " ").replace("Z", "")
                return (0, t)
            video_infos = sorted(video_infos, key=get_chrono_key)


            # --- QUALITY ANALYSIS ---
            import sys
            from pathlib import Path
            root_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
            if root_dir not in sys.path:
                sys.path.append(root_dir)
            from quality import analyze_all_videos_quality
            video_quality_map = analyze_all_videos_quality(video_infos)
            
            # Export quality map for reuse in Phase 2
            try:
                from app.services.storage_service import storage_service
                export_map = {Path(k).name: v for k, v in video_quality_map.items()}
                quality_key = f"projects/{project_id}/jobs/{job_uuid}/quality_map.json"
                storage_service.upload_json(export_map, quality_key)
                logging.info(f"  [quality] Exported quality map to MinIO ({quality_key})")
            except Exception as e:
                logging.warning(f"  [quality] Failed to export quality map to MinIO: {e}")
            # ------------------------
            # --- STORY CONTEXT ANALYSIS ---
            update_progress(15)
            story_context = run_story_context_analysis(video_infos, vibe, directives, tmpdir)
            
            if story_context:
                async def _save_story_context():
                    async with TaskSessionLocal() as db:
                        result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == job_uuid))
                        job = result.scalar_one_or_none()
                        if job:
                            job.story_summary = story_context.get("story_summary")
                            job.proposed_asset_order = story_context.get("asset_order")
                            job.asset_phases = story_context.get("asset_phases")
                            job.status = JobStatus.STORY_PROPOSED
                            job.progress = 20
                            await db.commit()
                loop.run_until_complete(_save_story_context())
                logging.info(f"  ✓ Phase 1 complete: Story proposed for Job {job_id}. Pausing for user confirmation.")
                return
            # ------------------------------

            total = len(video_infos)
            completed = [0]
            lock = threading.Lock()
            def on_video_done():
                with lock:
                    completed[0] += 1
                    p = 20 + int((completed[0] / total) * 60) if total else 80
                    update_progress(p)

            try:
                final_segs, _all_results = run_full_analysis(
                    video_infos,
                    api_key=settings.NVIDIA_API_KEY,
                    video_quality_map=video_quality_map,
                    reference_paths=[],
                    directives=directives,
                    progress_callback=on_video_done,
                    story_context=story_context
                )
                
                update_progress(90)
                async def _save_results(segs):
                    async with TaskSessionLocal() as db:
                        for idx, seg in enumerate(segs):
                            asset_id_str = seg.get("asset_id")
                            if asset_id_str:
                                m_asset = next((a for a in media_assets if str(a["id"]) == asset_id_str), media_assets[0])
                            else:
                                v_idx = int(seg.get("video_idx", 0))
                                m_asset = media_assets[v_idx] if v_idx < len(media_assets) else media_assets[0]
                            
                            clip = AnalyzedClip(
                                job_id=job_uuid,
                                media_asset_id=uuid.UUID(str(m_asset["id"])),
                                start_sec=float(seg.get("start_sec", 0.0)),
                                end_sec=float(seg.get("end_sec", 0.0)),
                                story_position=idx,
                                metadata_json=seg,
                                is_used=bool(seg.get("is_used", True))
                            )
                            db.add(clip)
                        await db.commit()
                
                loop.run_until_complete(_save_results(final_segs))
                
                # Stitch the segments into a final video summary and upload to MinIO
                logging.info("  🎬 [Pipeline] Generating final stitched video summary...")
                clips_dir = Path(tmpdir) / "clips"
                reel_path = Path(tmpdir) / "final_video.mp4"
                
                from app.services.stitch_service import build_reel_from_segments
                
                build_reel_from_segments(final_segs, clips_dir, reel_path)
                
                # Check for music integration
                if music_config and music_config.get("mode") != "none":
                    logging.info(f"  🎵 [Pipeline] Running music selection flow. Mode: {music_config.get('mode')}")
                    from app.services.music_service import resolve_custom_music, pick_ai_music, mix_music_into_video, resolve_suno_music
                    from app.services.spotify_service import get_spotify_hookline_start
                    import os
                    
                    music_path = None
                    song_title = ""
                    if music_config.get("mode") == "custom" and music_config.get("custom_query"):
                        music_path, song_title = resolve_custom_music(music_config["custom_query"], tmpdir)
                    elif music_config.get("mode") == "ai":
                        music_path, song_title = pick_ai_music(vibe, final_segs, tmpdir)
                    elif music_config.get("mode") == "suno":
                        music_path = resolve_suno_music(
                            vibe=vibe,
                            final_segs=final_segs,
                            instrumental=music_config.get("instrumental", True),
                            tmpdir=tmpdir
                        )
                        if not music_path:
                            logging.warning("Suno AI failed (likely 429 Insufficient Credits). Falling back to royalty-free 'ai' music.")
                            music_path, song_title = pick_ai_music(vibe, final_segs, tmpdir)

                        
                    if music_path and os.path.exists(music_path):
                        # Detect hookline start via Spotify (falls back to 0.0 safely if unavailable)
                        hook_start = get_spotify_hookline_start(song_title) if song_title else 0.0
                        logging.info(f"  🎵 [Pipeline] Music resolved to local path: {music_path}. Hookline start: {hook_start:.1f}s. Mixing...")
                        mixed_reel_path = Path(tmpdir) / "final_video_mixed.mp4"
                        try:
                            mix_music_into_video(str(reel_path), music_path, str(mixed_reel_path), audio_start=hook_start)
                            if mixed_reel_path.exists():
                                reel_path = mixed_reel_path
                                logging.info("  🎵 [Pipeline] Music successfully mixed into reel video.")
                            else:
                                logging.warning("  ⚠️ [Pipeline] Mixed video was not created, falling back to silent video.")
                        except Exception as mix_err:
                            logging.error(f"  ❌ [Pipeline] Failed to mix music into video: {mix_err}. Falling back to silent video.")
                    else:
                        logging.warning("  ⚠️ [Pipeline] Music path could not be resolved. Falling back to silent video.")
                
                if reel_path.exists():
                    logging.info("  📤 [Pipeline] Uploading final video to MinIO...")
                    object_key = f"projects/{project_id}/jobs/{job_id}/final_video.mp4"
                    with open(reel_path, "rb") as video_file:
                        storage_service.upload_file_obj(video_file, object_key, content_type="video/mp4")
                    logging.info(f"  ✅ [Pipeline] Final video uploaded to MinIO: {object_key}")
                else:
                    raise FileNotFoundError("Final video file was not created by stitcher.")
                
                update_progress(100, JobStatus.COMPLETED)
                
            except Exception as e:
                import traceback
                err = traceback.format_exc()
                update_progress(0, JobStatus.FAILED, error=str(e))
                raise

    finally:
        loop.run_until_complete(task_engine.dispose())
        loop.close()


@celery_app.task(bind=True)
def continue_video_analysis(self, job_id: str, confirmed_order: list, confirmed_summary: str, confirmed_phases: dict, music_config: dict = None):
    import uuid
    import asyncio
    import os
    import requests
    import tempfile
    import threading
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy.pool import NullPool
    from sqlalchemy.orm import selectinload
    from app.core.config import settings
    from app.models.domain import AnalysisJob, Project, AnalyzedClip, JobStatus
    
    job_uuid = uuid.UUID(job_id)

    task_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, echo=False)
    TaskSessionLocal = async_sessionmaker(task_engine, expire_on_commit=False)
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def _update_progress(p: int, status: JobStatus = None, error: str = None):
        async with TaskSessionLocal() as db:
            result = await db.execute(select(AnalysisJob).filter(AnalysisJob.id == job_uuid))
            job = result.scalar_one_or_none()
            if job:
                job.progress = p
                if status:
                    job.status = status
                if error:
                    job.error_message = error
                await db.commit()

    def update_progress(p: int, status: JobStatus = None, error: str = None):
        loop.run_until_complete(_update_progress(p, status, error))

    try:
        update_progress(25, JobStatus.RUNNING)
        
        async def _get_job_details():
            async with TaskSessionLocal() as db:
                result = await db.execute(
                    select(AnalysisJob)
                    .options(selectinload(AnalysisJob.project).selectinload(Project.media_assets))
                    .filter(AnalysisJob.id == job_uuid)
                )
                job = result.scalar_one_or_none()
                if not job:
                    raise ValueError(f"Job {job_id} not found.")
                
                project_id = str(job.project_id)
                vibe = job.vibe or "cinematic"
                sorted_assets = sorted(
                    [a for a in job.project.media_assets if not a.is_deleted],
                    key=lambda a: a.sequence_index
                )

                media_assets = [
                    {
                        "id": str(asset.id),
                        "file_name": asset.filename,
                        "storage_path": asset.object_key,
                    }
                    for asset in sorted_assets
                ]
                return project_id, vibe, media_assets
                
        project_id, vibe, media_assets = loop.run_until_complete(_get_job_details())
        
        from app.services.logger_service import init_run_log_dir
        init_run_log_dir(project_id, job_id)
        logging.info(f"  🎬 [Pipeline Phase 2] Continuing analysis for job {job_id} | vibe={vibe!r}")

        with tempfile.TemporaryDirectory() as tmpdir:
            video_paths = []
            from app.services.storage_service import storage_service
            for idx, asset in enumerate(media_assets):
                ext = asset.get('file_name', '').split('.')[-1]
                if not ext:
                    ext = 'mp4'
                local_path = os.path.join(tmpdir, f"asset_{idx}.{ext}")
                presigned = storage_service.generate_presigned_url(asset["storage_path"])
                r = requests.get(presigned)
                
                if r.status_code != 200:
                    logging.error(f"  ❌ Failed to download {asset.get('file_name', 'unknown')} (status={r.status_code}) from MinIO.")
                    continue
                    
                with open(local_path, "wb") as f:
                    f.write(r.content)
                
                video_paths.append(local_path)
                
            video_infos = []
            for idx, vp in enumerate(video_paths):
                info = get_video_info(vp)
                if info:
                    info["asset_id"] = media_assets[idx]["id"]
                    info["filename"] = media_assets[idx]["file_name"]
                    video_infos.append(info)

            # Sort video_infos chronologically by creation_time to ensure chronological story order mapping
            def get_chrono_key(x):
                ct = x.get("creation_time")
                if not ct:
                    return (1, "")
                # Normalize time string to make it comparable
                t = str(ct).strip().replace(":", "-").replace("T", " ").replace("Z", "")
                return (0, t)
            video_infos = sorted(video_infos, key=get_chrono_key)


            # --- QUALITY ANALYSIS ---
            import sys
            from pathlib import Path
            root_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
            if root_dir not in sys.path:
                sys.path.append(root_dir)
            from quality import analyze_all_videos_quality
            
            video_quality_map = {}
            try:
                from app.services.storage_service import storage_service
                quality_key = f"projects/{project_id}/jobs/{job_uuid}/quality_map.json"
                export_map = storage_service.download_json(quality_key)
                
                if export_map:
                    for info in video_infos:
                        filename = Path(info["path"]).name
                        if filename in export_map:
                            video_quality_map[info["path"]] = export_map[filename]
                    logging.info(f"  [quality] Successfully restored quality map from MinIO for {len(video_quality_map)} videos.")
            except Exception as e:
                logging.warning(f"  [quality] Failed to restore quality map from MinIO: {e}")
                
            if not video_quality_map:
                logging.info("  [quality] Running full quality analysis from scratch...")
                video_quality_map = analyze_all_videos_quality(video_infos)
            # ------------------------

            total = len(video_infos)
            completed = [0]
            lock = threading.Lock()
            def on_video_done():
                with lock:
                    completed[0] += 1
                    p = 25 + int((completed[0] / total) * 55) if total else 80
                    update_progress(p)

            try:
                story_context = {
                    "story_summary": confirmed_summary,
                    "asset_order": confirmed_order,
                    "asset_phases": confirmed_phases
                }
                
                final_segs, _all_results = run_full_analysis(
                    video_infos,
                    api_key=settings.NVIDIA_API_KEY,
                    video_quality_map=video_quality_map,
                    reference_paths=[],
                    directives="",
                    progress_callback=on_video_done,
                    story_context=story_context
                )
                
                update_progress(85)
                async def _save_results(segs):
                    async with TaskSessionLocal() as db:
                        for idx, seg in enumerate(segs):
                            result = await db.execute(
                                select(Project).options(selectinload(Project.media_assets)).filter(Project.id == uuid.UUID(project_id))
                            )
                            proj = result.scalar_one()
                            db_assets = sorted(
                                [a for a in proj.media_assets if not a.is_deleted],
                                key=lambda a: a.sequence_index
                            )
                            
                            asset_id_str = seg.get("asset_id")
                            if asset_id_str:
                                m_asset = next((a for a in db_assets if str(a.id) == asset_id_str), db_assets[0])
                            else:
                                v_idx = int(seg.get("video_idx", 0))
                                m_asset = db_assets[v_idx] if v_idx < len(db_assets) else db_assets[0]
                            
                            clip = AnalyzedClip(
                                job_id=job_uuid,
                                media_asset_id=m_asset.id,
                                start_sec=float(seg.get("start_sec", 0.0)),
                                end_sec=float(seg.get("end_sec", 0.0)),
                                story_position=idx,
                                metadata_json=seg,
                                is_used=bool(seg.get("is_used", True))
                            )
                            db.add(clip)
                        await db.commit()
                
                loop.run_until_complete(_save_results(final_segs))
                
                # Stitch the segments into a final video summary and upload to MinIO
                logging.info("  🎬 [Pipeline Phase 2] Generating final stitched video summary...")
                clips_dir = Path(tmpdir) / "clips"
                reel_path = Path(tmpdir) / "final_video.mp4"
                
                from app.services.stitch_service import build_reel_from_segments
                build_reel_from_segments(final_segs, clips_dir, reel_path)
                
                # Check for music integration
                if music_config and music_config.get("mode") != "none":
                    logging.info(f"  🎵 [Pipeline Phase 2] Running music selection flow. Mode: {music_config.get('mode')}")
                    from app.services.music_service import resolve_custom_music, pick_ai_music, mix_music_into_video, resolve_suno_music
                    from app.services.spotify_service import get_spotify_hookline_start
                    
                    music_path = None
                    song_title = ""
                    if music_config.get("mode") == "custom" and music_config.get("custom_query"):
                        music_path, song_title = resolve_custom_music(music_config["custom_query"], tmpdir)
                    elif music_config.get("mode") == "ai":
                        music_path, song_title = pick_ai_music(vibe, final_segs, tmpdir)
                    elif music_config.get("mode") == "suno":
                        music_path = resolve_suno_music(
                            vibe=vibe,
                            final_segs=final_segs,
                            instrumental=music_config.get("instrumental", True),
                            tmpdir=tmpdir
                        )
                        if not music_path:
                            logging.warning("Suno AI failed (likely 429 Insufficient Credits). Falling back to royalty-free 'ai' music.")
                            music_path, song_title = pick_ai_music(vibe, final_segs, tmpdir)
                        
                    if music_path and os.path.exists(music_path):
                        # Detect hookline start via Spotify (falls back to 0.0 safely if unavailable)
                        hook_start = get_spotify_hookline_start(song_title) if song_title else 0.0
                        logging.info(f"  🎵 [Pipeline Phase 2] Music resolved to local path: {music_path}. Hookline start: {hook_start:.1f}s. Mixing...")
                        mixed_reel_path = Path(tmpdir) / "final_video_mixed.mp4"
                        try:
                            mix_music_into_video(str(reel_path), music_path, str(mixed_reel_path), audio_start=hook_start)
                            if mixed_reel_path.exists():
                                reel_path = mixed_reel_path
                                logging.info("  🎵 [Pipeline Phase 2] Music successfully mixed.")
                        except Exception as mix_err:
                            logging.error(f"  ❌ Failed to mix music: {mix_err}")
                
                if reel_path.exists():
                    logging.info("  📤 [Pipeline Phase 2] Uploading final video to MinIO...")
                    object_key = f"projects/{project_id}/jobs/{job_id}/final_video.mp4"
                    with open(reel_path, "rb") as video_file:
                        storage_service.upload_file_obj(video_file, object_key, content_type="video/mp4")
                    logging.info(f"  ✅ [Pipeline Phase 2] Final video uploaded: {object_key}")
                else:
                    raise FileNotFoundError("Final video file was not created by stitcher.")
                
                update_progress(100, JobStatus.COMPLETED)
                
            except Exception as e:
                update_progress(0, JobStatus.FAILED, error=str(e))
                raise
                
    finally:
        loop.run_until_complete(task_engine.dispose())
        loop.close()


@celery_app.task(bind=True)
def render_project_from_template(self, project_id: str, job_id: str, template_id: str, slots: list):
    """
    Renders a video according to a locked template specification.
    `slots` is a list of dicts: {"slot_id": str, "object_key": str or None, "text": str or None}
    """
    import asyncio
    import os
    import json
    import tempfile
    import requests
    import logging
    import uuid
    from pathlib import Path
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from sqlalchemy import update
    from sqlalchemy.pool import NullPool
    
    from app.core.config import settings
    from app.models.domain import AnalysisJob, JobStatus
    from app.services.storage_service import storage_service
    from app.services.stitch_service import trim_and_normalize_clip, build_reel_from_segments
    
    # Establish a local task loop
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    task_engine = create_async_engine(settings.DATABASE_URL, poolclass=NullPool, echo=False)
    TaskSessionLocal = async_sessionmaker(task_engine, expire_on_commit=False)
    
    async def _update_progress(p: int, status: JobStatus = None, error: str = None):
        async with TaskSessionLocal() as session:
            stmt = update(AnalysisJob).where(AnalysisJob.id == uuid.UUID(job_id)).values(progress=p)
            if status:
                stmt = stmt.values(status=status)
            if error:
                stmt = stmt.values(error_message=error)
            await session.execute(stmt)
            await session.commit()
            
    def update_progress(p: int, status: JobStatus = None, error: str = None):
        loop.run_until_complete(_update_progress(p, status, error))
        
    try:
        update_progress(10, JobStatus.RUNNING)
        logging.info(f"🎬 [Template Engine] Starting render job {job_id} | project={project_id} | template={template_id}")
        
        # 1. Load the template definition
        templates_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "templates")
        template_path = os.path.join(templates_dir, f"{template_id}.json")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template {template_id} definition not found.")
            
        with open(template_path, "r", encoding="utf-8") as f:
            template = json.load(f)
            
        # 2. Match user input to template slots and download files
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir_path = Path(tmpdir)
            processed_segments = []
            
            # slots: [{"slot_id": str, "object_key": str or None, "text": str or None}]
            user_slots = {s["slot_id"]: s for s in slots}
            
            story_position = 0
            for slot_conf in template["slots"]:
                slot_id = slot_conf["id"]
                user_input = user_slots.get(slot_id)
                
                # Check if slot is deleted/omitted
                if not user_input or not user_input.get("object_key"):
                    if slot_conf.get("deletable", False):
                        logging.info(f"🎬 [Template Engine] Skipping deleted slot: {slot_id}")
                        continue
                    else:
                        raise ValueError(f"Required slot {slot_id} is missing an asset mapping.")
                        
                # Download media asset
                object_key = user_input["object_key"]
                ext = object_key.split('.')[-1] if '.' in object_key else 'mp4'
                local_raw_path = temp_dir_path / f"raw_{slot_id}.{ext}"
                
                logging.info(f"🎬 [Template Engine] Downloading {object_key} for {slot_id}...")
                presigned = storage_service.generate_presigned_url(object_key)
                r = requests.get(presigned)
                if r.status_code != 200:
                    raise RuntimeError(f"Failed to download asset {object_key} from storage.")
                with open(local_raw_path, "wb") as f:
                    f.write(r.content)
                    
                # Get duration from tracks array instead of slot config
                slot_id = slot_conf["id"]
                slot_tracks = [t for t in template.get("tracks", []) if t.get("slot_id") == slot_id and t["type"] == "video"]
                duration = max((t["end"] - t["start"]) for t in slot_tracks) if slot_tracks else 5.0
                # Always pass user-supplied text; the renderer uses it if set,
                # regardless of whether the slot config has text_overlay defined
                # (text config lives in the tracks array for landscape-style templates)
                custom_text = user_input.get("text")
                
                processed_segments.append({
                    "video_path": str(local_raw_path),
                    "start_sec": 0.0,
                    "end_sec": duration,
                    "story_position": story_position,
                    "story_role": "clip",
                    "text": custom_text,
                    "slot_id": slot_id,
                    "next_transition": slot_conf.get("transition_out", "fade"),
                    "next_transition_duration": 0.5
                })
                story_position += 1
                
            update_progress(50)
            
            # 3. Trim each clip and burn text overlays if configured.
            # IMPORTANT: For templates with a "tracks" array the universal renderer
            # handles text drawing at canvas-space coordinates. Do NOT burn text at
            # the clip level here — it will end up at the wrong position/size because
            # each clip is later cropped to a small strip on the canvas.
            clips_dir = temp_dir_path / "clips"
            clips_dir.mkdir(exist_ok=True)
            ordered_clip_paths = []
            uses_universal_renderer = "tracks" in template

            for idx, seg in enumerate(processed_segments):
                out_clip_path = clips_dir / f"clip_{idx:02d}.mp4"
                # Only burn clip-level text for non-universal (linear) templates
                clip_text = None if uses_universal_renderer else seg["text"]
                logging.info(f"🎬 [Template Engine] Trimming slot {idx} to {seg['end_sec']}s (Text: {seg['text']})...")
                trim_and_normalize_clip(
                    video_path=seg["video_path"],
                    start_sec=seg["start_sec"],
                    end_sec=seg["end_sec"],
                    out_path=out_clip_path,
                    text=clip_text
                )
                ordered_clip_paths.append(str(out_clip_path))
                
            update_progress(70)
            
            # 4. Stitch clips together
            layout_mode = template.get("layout_mode", "linear")
            
            if "tracks" in template:
                logging.info("🎬 [Template Engine] Using universal renderer...")
                from app.services.universal_renderer import render_universal_template
                
                # Map user custom texts from slots payload onto template text tracks
                for track in template.get("tracks", []):
                    if track.get("type") == "text":
                        track_slot_id = track.get("slot_id")
                        if track_slot_id in user_slots:
                            user_text = user_slots[track_slot_id].get("text")
                            if user_text is not None:
                                if "content" not in track:
                                    track["content"] = {}
                                track["content"]["value"] = user_text
                                logging.info(f"📝 [Template Engine] Set text for {track_slot_id}: '{user_text}'")

                clip_paths = {
                    seg["slot_id"]: ordered_clip_paths[idx]
                    for idx, seg in enumerate(processed_segments)
                }
                reel_path = temp_dir_path / "stitched_reel.mp4"
                render_universal_template(
                    clip_paths=clip_paths,
                    output_path=str(reel_path),
                    template=template,
                )
            elif layout_mode == "beat_grid":
                logging.info("🎬 [Template Engine] Using beat-grid renderer...")
                from app.services.beat_grid_renderer import render_beat_grid_template
                
                # Build { slot_id: local_clip_path } map
                clip_paths = {
                    seg["slot_id"]: ordered_clip_paths[idx]   # ✅ trimmed file
                    for idx, seg in enumerate(processed_segments)
                }
                reel_path = temp_dir_path / "stitched_reel.mp4"
                render_beat_grid_template(
                    clip_paths=clip_paths,
                    output_path=str(reel_path),
                    section_config=template["sections"],
                )
            else:
                reel_path = temp_dir_path / "stitched_reel.mp4"
                transitions = [seg["next_transition"] for seg in processed_segments[:-1]]
                transition_durations = [0.5] * len(transitions)
                
                stitched_segments = []
                for idx, clip_p in enumerate(ordered_clip_paths):
                    stitched_segments.append({
                        "video_path": clip_p,
                        "start_sec": 0.0,
                        "end_sec": processed_segments[idx]["end_sec"],
                        "story_position": idx,
                        "is_used": True
                    })
                    
                build_reel_from_segments(
                    best_segments=stitched_segments,
                    clips_dir=temp_dir_path / "stitch_temp",
                    reel_path=reel_path,
                    transitions=transitions,
                    transition_durations=transition_durations
                )
            
            update_progress(85)
            
            # 5. Mix music background
            music_mode = template.get("music_mode", "ai")
            music_query = template.get("music_query")
            music_file  = template.get("music_file")  # relative path for static mode

            if music_mode == "static" and music_file:
                # Use a bundled local audio file (relative to backend root)
                backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                static_music_path = os.path.join(backend_root, music_file)
                if os.path.exists(static_music_path):
                    logging.info(f"🎵 [Template Engine] Using static music: {static_music_path}")
                    mixed_reel_path = temp_dir_path / "final_video_mixed.mp4"
                    try:
                        from app.services.music_service import mix_music_into_video
                        mix_music_into_video(str(reel_path), static_music_path, str(mixed_reel_path))
                        if mixed_reel_path.exists():
                            reel_path = mixed_reel_path
                            logging.info("🎵 [Template Engine] Static music successfully mixed.")
                    except Exception as mix_err:
                        logging.error(f"❌ [Template Engine] Failed to mix static music: {mix_err}")
                else:
                    logging.warning(f"⚠️ [Template Engine] Static music file not found: {static_music_path}. Skipping music.")

            elif music_mode != "none" and music_query:
                logging.info(f"🎵 [Template Engine] Adding template music background: {music_query}...")
                from app.services.music_service import resolve_custom_music, mix_music_into_video
                music_path = resolve_custom_music(music_query, tmpdir, skip_llm_expand=True)
                if music_path and os.path.exists(music_path):
                    mixed_reel_path = temp_dir_path / "final_video_mixed.mp4"
                    try:
                        mix_music_into_video(str(reel_path), music_path, str(mixed_reel_path))
                        if mixed_reel_path.exists():
                            reel_path = mixed_reel_path
                            logging.info("🎵 [Template Engine] Music successfully mixed.")
                    except Exception as mix_err:
                        logging.error(f"❌ [Template Engine] Failed to mix music: {mix_err}")
                        
            # 6. Upload final video back to MinIO
            if reel_path.exists():
                logging.info("📤 [Template Engine] Uploading final output to MinIO...")
                object_key = f"projects/{project_id}/jobs/{job_id}/final_video.mp4"
                with open(reel_path, "rb") as video_file:
                    storage_service.upload_file_obj(video_file, object_key, content_type="video/mp4")
                logging.info(f"✅ [Template Engine] Video uploaded: {object_key}")
            else:
                raise FileNotFoundError("Final video was not found.")
                
            update_progress(100, JobStatus.COMPLETED)
            
    except Exception as e:
        import traceback
        logging.error(f"❌ [Template Engine] Job failed: {e}\n{traceback.format_exc()}")
        update_progress(0, JobStatus.FAILED, error=str(e))
        raise
        
    finally:
        loop.run_until_complete(task_engine.dispose())