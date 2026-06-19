"""
prompts.py — LLM prompt builders.

Philosophy: Make the model THINK like a master editor, not a describer.
  - Force explicit reasoning BEFORE any clip selection
  - Dedup through a mandatory "location inventory" step
  - Sequence through a mandatory "journey phase assignment" step
  - Reduce rules to principles the model can internalize
"""

import re
import json
from pathlib import Path


# ── JSON Parser ───────────────────────────────────────────────────────────────

def repair_json_string(text: str) -> str:
    # Remove any markdown code block wrappers
    text = re.sub(r"```json|```", "", text).strip()
    
    # Find the first '{'
    start_idx = text.find('{')
    if start_idx == -1:
        return text
    text = text[start_idx:]
    
    # Repair mismatched brackets/braces
    stack = []
    in_string = False
    escape = False
    repaired_chars = []
    
    for i, char in enumerate(text):
        if escape:
            repaired_chars.append(char)
            escape = False
            continue
        if char == '\\':
            repaired_chars.append(char)
            escape = True
            continue
        if char == '"':
            repaired_chars.append(char)
            in_string = not in_string
            continue
            
        if in_string:
            repaired_chars.append(char)
            continue
            
        if char in ('{', '['):
            stack.append(char)
            repaired_chars.append(char)
        elif char == '}':
            while stack and stack[-1] == '[':
                stack.pop()
                repaired_chars.append(']')
            if stack and stack[-1] == '{':
                stack.pop()
            repaired_chars.append(char)
        elif char == ']':
            while stack and stack[-1] == '{':
                stack.pop()
                repaired_chars.append('}')
            if stack and stack[-1] == '[':
                stack.pop()
            repaired_chars.append(char)
        else:
            repaired_chars.append(char)
            
    while stack:
        top = stack.pop()
        if top == '{':
            repaired_chars.append('}')
        elif top == '[':
            repaired_chars.append(']')
            
    return "".join(repaired_chars)


def parse_json_response(text: str) -> dict:
    if text is None:
        raise ValueError("Model returned None — empty response from API")
    # Strip <think> blocks (models that use explicit tags)
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    # Strip markdown code fences
    text = re.sub(r"```json|```", "", text).strip()
    # Strip any reasoning preamble before the first { (plain-text thinking leak)
    first_brace = text.find("{")
    if first_brace > 0:
        text = text[first_brace:]
    try:
        return json.loads(text)
    except Exception:
        pass

    # Try repairing the JSON string before other attempts
    try:
        repaired = repair_json_string(text)
        return json.loads(repaired)
    except Exception:
        pass

    # Balanced bracket matching to extract first valid complete JSON object (preferring last if multiple exist)
    open_indices = [i for i, c in enumerate(text) if c == '{']
    for start in reversed(open_indices):
        count = 0
        for end in range(start, len(text)):
            if text[end] == '{':
                count += 1
            elif text[end] == '}':
                count -= 1
                if count == 0:
                    substring = text[start:end+1]
                    try:
                        parsed = json.loads(substring)
                        if isinstance(parsed, dict) and ("best_segments" in parsed or "journey_phase" in parsed or "location_tag" in parsed or "order" in parsed):
                            return parsed
                    except Exception:
                        pass
                    break

    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"No JSON object found in:\n{text[:500]}")
    try:
        return json.loads(m.group(0))
    except Exception:
        pass

    try:
        repaired_regex = repair_json_string(m.group(0))
        return json.loads(repaired_regex)
    except Exception as e:
        raise ValueError(f"Could not parse repaired JSON: {e}. Raw matching block:\n{m.group(0)}")


def clamp_segments(segments: list, duration: float) -> list:
    """Validate and clamp segment time boundaries to [0, duration]."""
    valid = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        try:
            start_val = seg.get("start_sec", 0.0)
            if isinstance(start_val, str):
                start_val = start_val.strip()
                if start_val.lower() in ("float", "double", "int", ""):
                    start_val = 0.0
            start = max(0.0, float(start_val))
        except (ValueError, TypeError):
            start = 0.0

        try:
            end_val = seg.get("end_sec", duration)
            if isinstance(end_val, str):
                end_val = end_val.strip()
                if end_val.lower() in ("float", "double", "int", ""):
                    end_val = duration
            end = min(float(duration), float(end_val))
        except (ValueError, TypeError):
            end = duration

        if end > start:
            seg["start_sec"] = round(start, 2)
            seg["end_sec"]   = round(end,   2)
            valid.append(seg)
    return valid


# ── Timeline Prompt ────────────────────────────────────────────────────────────

def build_timeline_prompt(
    video_info: dict,
    frame_meta: list,
    reference_images: list,
    video_quality_map: dict,
    directives: str = "",
    audio_analysis: dict = None,
) -> str:
    directives_note = ""
    if directives:
        directives_note = f"\nUSER EDITING DIRECTIVES (YOU MUST FOLLOW THESE INSTRUCTIONS):\n{directives}\n"

    audio_note = ""
    if audio_analysis:
        audio_note = f"""
BACKGROUND MUSIC ANALYSIS (YOU MUST ALIGN YOUR CLIP SELECTION WITH THESE HOOKS):
Summary: {audio_analysis.get('music_summary', '')}
Vibe recommendation: {audio_analysis.get('vibe_recommendation', '')}
Hooks & Energy Peaks of the BGM:
"""
        for h in audio_analysis.get("hooks", []):
            audio_note += f"- {h.get('start_sec')}s to {h.get('end_sec')}s: {h.get('hook_type', 'peak')} ({h.get('energy_level', 'high')} energy) | Edit instruction: {h.get('editing_instruction', '')}\n"
        
        audio_note += "\nYour selection of 'best_segments' MUST align with this background music. Identify high-energy clips for hook/chorus timestamps, and softer setup/narrative clips for low-energy timestamps.\n"

    if video_info.get("is_image"):
        return f"""You are a master short-form video editor. Analyze this static photo for a viral social reel.
{directives_note}{audio_note}
Return ONLY valid JSON. No markdown, no code fences, no extra text.

{{
  "video_summary": "string",
  "camera_rotation": 0,
  "detected_scenario": "D",
  "overall_mood": "string",
  "overall_vibe": "string",
  "editor_reasoning": "string",
  "key_moments": [{{"timestamp_sec": 0.0, "description": "Static photo view"}}],
  "best_segments": [{{
    "start_sec": 0.0, "end_sec": 3.0,
    "what_happens": "string", "mood": "string",
    "energy": 3, "visual_quality": 8, "instagrammable": 8, "story_value": 8,
    "reason": "string", "priority": 1,
    "narrative_role": "setup | climax | detail | establishing_shot | payoff",
    "clip_type_applied": "Static photo",
    "location_tag": "snake_case_label",
    "journey_phase": "approach | arrival | exterior | interior | detail | climax",
    "time_of_day": "dawn | morning | afternoon | golden_hour | dusk | night | unknown",
    "scene_category": "scenery | people | action | food | vehicle | mixed",
    "primary_subjects": ["list of 1-3 prominent subjects: e.g. 'birthday girl', 'mountains'"]
  }}]
}}
"""

    qmap      = video_quality_map.get(video_info["path"], {})
    q_samples = qmap.get("samples", [])
    q_stats   = qmap.get("stats",   {})

    def nearest_quality(ts):
        if not q_samples:
            return None
        return min(q_samples, key=lambda s: abs(s["t"] - ts))

    # Frame lines: blur/shake/motion inline, concise format
    frame_lines = []
    for f in frame_meta:
        q = nearest_quality(f["timestamp_sec"])
        if q:
            mt = q.get("motion_type", "NORMAL")
            blurry = " BLURRY" if q.get("is_blurry") else ""
            frame_lines.append(
                f'frame_{f["frame_index"]:02d} @ {f["timestamp_sec"]}s '
                f'blur={q["blur_norm"]:.1f} shake={q["shake_norm"]:.1f} {mt}{blurry}'
            )
        else:
            frame_lines.append(f'frame_{f["frame_index"]:02d} @ {f["timestamp_sec"]}s')

    # Compact quality timeline: summary header + per-sample rows, no verbose legend
    quality_timeline = ""
    if q_samples:
        pct_shaky  = round(q_stats.get("n_shaky_samples",  0) / max(len(q_samples), 1) * 100)
        pct_blurry = round(q_stats.get("n_blurry_samples", 0) / max(len(q_samples), 1) * 100)
        mc = q_stats.get("motion_counts", {})

        quality_timeline = (
            f"\nQuality: {pct_shaky}% shaky, {pct_blurry}% blurry | motion={mc}\n"
            "Per-0.5s quality (blur 0-10 higher=sharper, shake 0-10 higher=shakier, avoid CHAOTIC/WHIP_PAN):\n"
        )
        step = 1
        if len(q_samples) > 60:
            step = 3
        elif len(q_samples) > 30:
            step = 2

        for i, s in enumerate(q_samples):
            if i % step != 0:
                continue
            mt    = s.get("motion_type", "NORMAL")
            extra = " BLURRY" if s.get("is_blurry") else ""
            quality_timeline += (
                f't={s["t"]:5.2f}s blur={s["blur_norm"]:4.1f} shake={s["shake_norm"]:4.1f} {mt}{extra}\n'
            )

    duration = round(video_info["duration_sec"], 2)

    ref_note = ""
    if reference_images:
        ref_note = (
            f"Reference photos ({len(reference_images)} attached): "
            "prefer matching people, aesthetic, and context.\n"
        )

    return f"""You are a master short-form video editor. Extract only the best moments for a viral social reel.
{directives_note}{audio_note}
Return ONLY valid JSON. No markdown, no code fences, no extra text.

Video duration: {duration}s.
{ref_note}{quality_timeline}
Frames (blur/shake/motion per frame):
{chr(10).join(frame_lines)}

Clip types — pick ONE:
- F: continuous architecture/nature reveal → take best 3s only
- D: uniformly strong short clip → take the whole clip
- E: partial highlight → trim to the strong window only
- B: multiple distinct moments → extract each strong moment separately
- C: single continuous action arc → take the full arc (1–4s)
- A: short single scene beat → take as one segment

Rules:
- Prefer SETTLED/LINEAR_FORWARD frames. Avoid CHAOTIC/WHIP_PAN frames.
- Reject: blurry-throughout, floor-only, empty walking-only shots.
- Clip Durations (CRITICAL PACING):
  - High-energy/active footage (e.g. sports, rapid movement): MUST be fast and dynamic, exactly 2.0–4.0 seconds (e.g. start=10.0, end=13.5).
  - Slower atmospheric/cinematic beauty shots (e.g. temples, landscapes, reflection): Let them linger, exactly 5.0–8.0 seconds (e.g. start=0.0, end=7.5).
  - All other clips (B-roll, scenery, setup, transition walking): MUST be 3.0–5.0 seconds. NEVER exceed 8.0 seconds.
- location_tag: snake_case label for the physical spot/subject (e.g. pool, table_tennis, garden, archway, city, temple_candles). Use the same tag for clips showing the same location/setting.
- journey_phase: approach|arrival|exterior|interior|detail|climax
- time_of_day: infer from lighting, sky color, shadows, and artificial light presence. dawn = soft pink/purple sky. morning = bright soft light, long shadows. afternoon = harsh overhead light. golden_hour = warm orange light, low sun. dusk = sky transitioning dark. night = dark sky, artificial lights dominant. If indoors with no sky visible, infer from light color temperature (warm tungsten = likely night, cool daylight = likely day).
- scene_category: Classify the dominant content of the clip. Options: scenery, people, action, food, vehicle, mixed.
- primary_subjects: List of 1-3 most visually prominent subjects (people by role/appearance like 'woman in yellow dress', objects, landmarks like 'temple dome'). Be specific, not generic.
- Prefer 1–3 strong segments. Max 5. Stay within {duration}s. Ensure the key narrative arc is represented: if the video has a clear celebratory, interactive, or conclusive payoff moment at the end, you MUST include a segment for it.
- YOU MUST include "best_segments" in the JSON output.
- CRITICAL: You MUST use real timestamps from the frames and real 1-10 scores instead of placeholder types.
- camera_rotation: Always set this to 0 (do not attempt to auto-rotate).

Return JSON:
{{
  "video_summary": "string — Describe the actual visual subjects, people, key objects, and activities in the video, plus a note on camera movement (1-2 sentences).",
  "camera_rotation": 0,
  "detected_scenario": "A|B|C|D|E|F",
  "overall_mood": "string",
  "overall_vibe": "string",
  "editor_reasoning": "string — what is visually in the video, camera action, best/worst moment",
  "key_moments": [{{
    "timestamp_sec": "float",
    "description": "string"
  }}],
  "best_segments": [{{
    "start_sec": "float (e.g., 2.5)", "end_sec": "float (e.g., 5.0)",
    "what_happens": "string — what specific visual subject/action is shown in this segment (e.g. driving a car, looking out at a white temple building)", "mood": "string",
    "energy": "integer (1-10)", "visual_quality": "integer (1-10)", "instagrammable": "integer (1-10)", "story_value": "integer (1-10)",
    "reason": "string",
    "priority": "integer (1-5)",
    "narrative_role": "setup|action|climax|reaction|payoff",
    "clip_type_applied": "string",
    "location_tag": "string",
    "journey_phase": "approach|arrival|exterior|interior|detail|climax",
    "time_of_day": "dawn | morning | afternoon | golden_hour | dusk | night | unknown",
    "scene_category": "string (scenery | people | action | food | vehicle | mixed)",
    "primary_subjects": ["string"]
  }}]
}}
"""


# ── Story Order Prompt ─────────────────────────────────────────────────────────

def build_focus_constraint(focus: dict) -> str:
    if not focus or not focus.get("type"):
        return ""
    
    if focus["type"] == "weight":
        pct = int(focus["weight"] * 100)
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOCUS CONSTRAINT (HARD RULE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Approximately {pct}% of selected clips MUST have scene_category = '{focus["category"]}'.
The remaining {100-pct}% can be any category. Do NOT exceed this ratio in either direction by more than 10%.
"""
    elif focus["type"] == "subject":
        return f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FOCUS CONSTRAINT (HARD RULE)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Prioritize clips where primary_subjects contains '{focus["subject"]}' or closely related subjects.
At least 70% of the final reel MUST feature this subject prominently.
Non-matching clips may only fill transitional/contextual roles.
"""
    return ""


def build_story_order_prompt(segments: list, all_results: list, directives: str = "", focus: dict = None, audio_analysis: dict = None, beat_windows: list = None) -> str:
    audio_note = ""
    if audio_analysis:
        audio_note = f"""
BACKGROUND MUSIC CONTEXT:
Summary: {audio_analysis.get('music_summary', '')}
Vibe recommendation: {audio_analysis.get('vibe_recommendation', '')}
Hooks & Energy Peaks of the BGM:
"""
        for h in audio_analysis.get("hooks", []):
            audio_note += f"- {h.get('start_sec')}s to {h.get('end_sec')}s: {h.get('hook_type', 'peak')} ({h.get('energy_level', 'high')} energy) | Edit instruction: {h.get('editing_instruction', '')}\n"
        
        audio_note += "\nYour final ordering of the clips MUST align with the background music's pace and energy flow. High-energy/action clips (roles like 'payoff', 'hook') should align with the high-energy hook/chorus sections of the song. Softer detail or establishing shots should align with the low-intensity sections.\n"

    # ─────────────────────────────────────────────────────────────
    # SOURCE VIDEO CONTEXT
    # ─────────────────────────────────────────────────────────────
    video_summaries = []

    for i, result in enumerate(all_results):
        summary = result['analysis'].get('video_summary', 'no summary')
        reasoning = result['analysis'].get('editor_reasoning', '')

        video_summaries.append(
            f"SOURCE {i} — '{Path(result['video_path']).stem}' ({round(result['duration_sec'],1)}s)\n"
            f"Summary: {summary}\n"
            f"Editor Read: {reasoning[:180] if reasoning else 'N/A'}"
        )

    # ─────────────────────────────────────────────────────────────
    # CLIP INVENTORY
    # ─────────────────────────────────────────────────────────────
    seg_lines = []

    for i, seg in enumerate(segments):
        dur = round(float(seg["end_sec"]) - float(seg["start_sec"]), 2)
        is_img_val = seg.get("is_image", False) or Path(seg.get("video_path", "")).suffix.lower() in (".jpg", ".jpeg", ".png", ".heic")
        clip_type = "Static Photo" if is_img_val else "Video"

        seg_lines.append({
            "index": i,
            "seg": seg,
            "dur": dur,
            "clip_type": clip_type,
            "reason": (seg.get("reason") or "")[:140],
            "similar_to": [],
        })

    # ── Similarity detection: flag clips with near-identical reason text ──────
    def _word_overlap(a: str, b: str) -> float:
        """Fraction of words in the shorter string that appear in the longer one."""
        wa = set(a.lower().split())
        wb = set(b.lower().split())
        if not wa or not wb:
            return 0.0
        return len(wa & wb) / min(len(wa), len(wb))

    SIMILAR_THRESHOLD = 0.55
    for i, a in enumerate(seg_lines):
        for j, b in enumerate(seg_lines):
            if j <= i:
                continue
            overlap = _word_overlap(a["reason"], b["reason"])
            if overlap >= SIMILAR_THRESHOLD:
                a["similar_to"].append(j)
                b["similar_to"].append(i)

    # ── Build final text lines with similarity warnings ───────────────────────
    final_seg_lines = []
    for entry in seg_lines:
        i   = entry["index"]
        seg = entry["seg"]
        similar_note = ""
        if entry["similar_to"]:
            similar_note = f"\n⚠️  SIMILAR TO: CLIP {', CLIP '.join(str(x).zfill(2) for x in entry['similar_to'])} — DO NOT place these back-to-back. Separate with a contrasting clip type."

        final_seg_lines.append(
            f"""
CLIP {i:02d}
Type: {entry['clip_type']}
Duration: {entry['dur']}s
Phase: {seg.get("journey_phase", "unknown")}
Location: {seg.get("location_tag", "unknown")}
Role: {seg.get("narrative_role", "unknown")}
Mood: {seg.get("overall_mood", "")}
Reason: {entry['reason']}{similar_note}
Source: {Path(seg.get("video_path", "unknown")).stem}
Editor Read: {(seg.get("editor_reasoning") or "")[:220] or "N/A"}
""".strip()
        )

    # ─────────────────────────────────────────────────────────────
    # FINAL PROMPT
    # ─────────────────────────────────────────────────────────────

    beat_windows_note = ""
    json_schema = ""

    if beat_windows:
        beat_lines = [f"Window {w['window_index']}: {w['start_sec']}s to {w['end_sec']}s (Dur: {w['duration']}s)" for w in beat_windows]
        beat_windows_note = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BEAT TIMELINE SLOTS (CRITICAL)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
The background music has been analyzed. The video MUST be cut precisely to these beat windows:
{chr(10).join(beat_lines)}

You MUST assign a specific clip from the inventory to EACH beat window.
CRITICAL RULE 1: Alternate sources. DO NOT assign two consecutive windows to clips from the same SOURCE video or image.
CRITICAL RULE 2: Match mood/duration to the window.
"""
        json_schema = """
{{
  "removed_clips": [
    {{
      "clip": 3,
      "reason": "visually repetitive"
    }}
  ],
  "full_story": "2-3 sentence cinematic description...",
  "beat_assignments": [
    {{
      "window_index": 0,
      "clip_index": 5,
      "reason": "This clip has a strong approach that fits the 1.5s opening window."
    }},
    {{
      "window_index": 1,
      "clip_index": 2,
      "reason": "Switching to a different source for contrast on the next beat."
    }}
  ],
  "reasoning": "Explain why the hook works and transitions...",
  "audio_reasoning": "Explain how the clip sequence specifically aligns with the music."
}}
"""
    else:
        json_schema = f"""
{{
  "removed_clips": [
    {{
      "clip": 3,
      "reason": "visually repetitive"
    }}
  ],
  "full_story": "2-3 sentence cinematic description...",
  "order": [4, 1, 0, 6, 2, 7, 5, 8],
  "roles": ["hook", "build", "payoff"],
  "energy_flow": ["dramatic", "calm", "epic"],
  "reasoning": "Explain why the hook works and transitions...",
  "audio_reasoning": "Explain how the clip sequence specifically aligns with the music."
}}
"""

    temporal_note = (
        "The clips below have already been pre-sorted into a day-to-night temporal flow by the system.\n"
        "Your job is NOT to completely reorder by time — that is already done.\n"
        "Make minimal swaps to ensure locations are grouped. Preserve the day → night flow unless an emotional reason is extremely compelling."
    )
    if directives:
        temporal_note = (
            "You have full freedom to reorder the clips to best satisfy the USER EDITING DIRECTIVES above.\n"
            "Prioritize the chronological flow, subject focus, or progression requested by the user."
        )

    directives_note = ""
    directives_reminder = ""
    loc_grouping_note = "Once all clips for one location finish playing, you move to the next location. Never go back to a previously finished location."
    if directives:
        directives_note = f"\nUSER EDITING DIRECTIVES (YOU MUST FOLLOW THESE INSTRUCTIONS):\n{directives}\n"
        directives_reminder = f"\n- CRITICAL: YOU MUST STRICTLY FOLLOW THESE USER EDITING DIRECTIVES:\n{directives}\n"
        loc_grouping_note = "Once all clips for one location finish playing, you move to the next location. Never go back to a previously finished location, EXCEPT when doing so is necessary to satisfy the USER EDITING DIRECTIVES (for instance, if the user explicitly asks to start and end with a plane/flight, or return to a location)."

    focus_constraint = build_focus_constraint(focus)

    if directives:
        return f"""
You are an elite cinematic short-form video editor.
{directives_note}{audio_note}
{focus_constraint}

CRITICAL INSTRUCTION FOR REASONING AND THINKING:
Keep your internal thinking process (the reasoning path before outputting JSON) extremely short, concise, and direct (maximum 3-4 sentences total). Do not write long explanations, nested logic, or repetitive drafts. Summarize your thoughts immediately and output the final JSON object.

You are editing a premium Instagram/TikTok travel reel from raw trip footage.

Your goal is to arrange and filter the clips to satisfy the USER EDITING DIRECTIVES above.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE VIDEOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{chr(10).join(video_summaries)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE CLIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{chr(10).join(final_seg_lines)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — REMOVE WEAK / REPETITIVE CLIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Duplicate/Repetitive Clips: If you have two clips that show visually similar action or subject (e.g. two pool jumps, two very similar garden views), apply the "Rule of One": select the single best version (clearest, best lighting, best action) and remove the duplicate by placing it in "removed_clips". This prevents the viewer's brain from switching off.
- Default action: Otherwise, KEEP the clip and find a good position for it. DO NOT completely exclude any source video unless instructed by the directives.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — BUILD THE ORDER BASED ON THE DIRECTIVES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You have full freedom to reorder the clips to best satisfy the USER EDITING DIRECTIVES above.
Prioritize the chronological flow, subject focus, or progression requested by the user.

- DEFINE A NARRATIVE TEMPLATE: Analyze the available clips (whether they are from a trip, party, vlog, or event) and choose an overarching narrative template (e.g., "Arrival to Departure", "Day to Night", "Setup to Peak Action to Aftermath").
- REORGANIZE THE "ACTS" (Logical Flow): Stop jumping between locations. Group your clips into three natural Acts to build a professional story flow based on your template:
  - Act I: Setup / The Beginning (Establishing the scene, hook, arrival).
  - Act II: The Core Experience / Peak (The main event, highest energy, primary activities).
  - Act III: Conclusion / Reflection (The winding down, aftermath, or satisfying closure).
- STRICT LOCATION GROUPING: Within and across the Acts, you MUST group clips from the same physical location/scene together as a contiguous block. Once you show a location, play all clips from that location before moving on. Do NOT jump back and forth between locations (e.g., location A -> location B -> location A is strictly forbidden).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 — CHOOSE FLUID AND EMOTIONAL TRANSITIONS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For the transitions between consecutive clips, apply specific editing logic:
- The Cross-Dissolve ("dissolve"): Use this ONLY as a bridge when transitioning from one "Act" to the next (e.g., from city architecture into the boat ride).
- The Zoom-In ("zoom_in" or "zoom_dissolve"): Use this INSIDE the Acts to emphasize exciting action (e.g., as someone hits the water/pool, or hits a table tennis ball).
- The Cut ("cut"): Use this as the default for cuts within the same location/scene to keep the pacing dynamic.
- The Fade ("fade"): Use this at the very start/end of the video. Do not use intermediate fades elsewhere.
- Set transition durations appropriately (e.g. 0.2s - 0.3s for fast action, 0.4s - 0.5s for slower dissolves/fades).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON.
No markdown.
No explanations outside JSON.
No code fences.

{{
  "removed_clips": [],
  "narrative_template": "State the overarching template you chose (e.g., 'Arrival to Departure', 'Day to Night', etc.)",
  "full_story": "2-3 sentence cinematic description of the emotional progression of the reel",
  "order": [4, 1, 0, 6, 2, 7, 5, 8], // MUST contain ALL survived clip indices.
  "roles": ["hook", "build", "build", "build", "build", "build", "build", "payoff"],
  "energy_flow": ["dramatic", "movement", "calm", "atmospheric", "steady", "curious", "intense", "epic"],
  "transitions": ["fade", "zoom_dissolve", "dissolve", "cut", "zoom_in", "fade", "circle_crop"], // Transition name between consecutive clips in order. Length MUST be exactly len(order) - 1. Choose mostly FLUID transitions: fade, dissolve, zoom_dissolve, zoom_in, zoom_out, circle_crop, cut (50ms micro-fade). Avoid wipes/slides unless high-action.
  "transition_durations": [0.5, 0.4, 0.5, 0.05, 0.5, 0.5, 0.5], // Duration of each transition in seconds. Length MUST be exactly len(order) - 1.
  "reasoning": "Explain how the sequence satisfies the USER EDITING DIRECTIVES."
}}

CRITICAL RULES:
- order and roles MUST be same length
- transitions and transition_durations MUST be of length (len(order) - 1)
- Choose mostly FLUID, organic transitions (fade, dissolve, zoom_dissolve, zoom_in, cut). Avoid wipes and slides unless representing continuous high-action sports footage (like pool action or ping pong play).
- no duplicate clips in order
- removed_clips MUST NOT appear in order
- You MUST include ALL clips in 'order' that you did not explicitly remove in 'removed_clips'. Do NOT drop clips silently.
- CLIP COUNT CHECK: There are {len(segments)} clips (indices 0 to {len(segments)-1}). Your 'order' array MUST contain exactly {len(segments)} minus len(removed_clips) indices.
- STRICT LOCATION GROUPING: Unless explicitly requested by the user's directives, you MUST group clips from the same physical location/scene together contiguously. Do NOT alternate or interleave locations. Once a location is shown, all clips from that location must finish playing before moving to the next.
- CRITICAL: YOU MUST STRICTLY FOLLOW THESE USER EDITING DIRECTIVES:
{directives}

CRITICAL REASONING CONSTRAINT: Your thinking block (<think>...</think>) MUST be under 100 tokens. Summarize in 3 sentences max, then immediately output the JSON.
"""

    return f"""
You are an elite cinematic short-form video editor.
{directives_note}{audio_note}
CRITICAL INSTRUCTION FOR REASONING AND THINKING:
Keep your internal thinking process (the reasoning path before outputting JSON) extremely short, concise, and direct (maximum 3-4 sentences total). Do not write long explanations, nested logic, or repetitive drafts. Summarize your thoughts immediately and output the final JSON object.

You are editing a premium Instagram/TikTok travel reel from raw trip footage.

Your goal is NOT to document the trip accurately.

Your goal is to create the MOST emotionally engaging reel possible.

Think like a real editor:
- viewer retention first
- emotional pacing first
- cinematic rhythm first
- visual contrast first

NOT strict chronology.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EDITOR MINDSET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

A great reel feels:
- cinematic
- emotionally progressive
- visually dynamic
- intentional
- immersive

The reel should feel like:
curiosity → movement → atmosphere → wonder → payoff

You are NOT organizing clips.

You are crafting emotion.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SOURCE VIDEOS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{chr(10).join(video_summaries)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
AVAILABLE CLIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{chr(10).join(final_seg_lines)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 — REMOVE WEAK / REPETITIVE CLIPS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

- Duplicate/Repetitive Clips: If you have two clips that show visually similar action or subject (e.g. two pool jumps, two very similar garden views), apply the "Rule of One": select the single best version (clearest, best lighting, best action) and remove the duplicate by placing it in "removed_clips". This prevents the viewer's brain from switching off.
- Otherwise, be conservative about removal. Do NOT remove clips just because they feel "less cinematic" or to keep the reel short. Every source video must contribute at least one clip if possible.
- Default action: KEEP the clip and find a good position for it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — BUILD THE EMOTIONAL ARC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{temporal_note}

Your job is ONLY to:
1. DEFINE A NARRATIVE TEMPLATE: Analyze the clips (whether they are from a trip, party, vlog, or event) and choose an overarching template (e.g., "Arrival to Departure", "Day to Night", "Calm to High Energy to Calm").
2. REORGANIZE THE "ACTS" (Logical Flow): Group your clips into three natural Acts based on your template:
   - Act I: Setup / The Beginning (Establishing the scene, hook, arrival).
   - Act II: The Core Experience / Peak (The main event, highest energy, primary activities).
   - Act III: Conclusion / Reflection (The winding down, aftermath, or satisfying closure).
3. Decide the best HOOK (first clip) within Act I.
4. Ensure no consecutive same-type clips (swap adjacent clips if needed).
5. Choose the best PAYOFF (final clip) within Act III.
6. STRICT LOCATION GROUPING: You MUST group clips from the same physical location/scene together as a contiguous block. Do NOT jump back and forth between locations (e.g. location A -> location B -> location A is strictly forbidden).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOOK RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The first clip MUST immediately create curiosity and make viewers stop scrolling.

CRITICAL RULE FOR STATIC PHOTOS:
- Static Photos (labeled "Type: Static Photo" in CLIP INVENTORY) have ZERO camera or subject motion and are terrible scroll-stoppers. They MUST NEVER be used as the HOOK (the very first clip in the reel)!
- The HOOK (the first clip in the reel) MUST always be a dynamic, high-impact Video (labeled "Type: Video") with solid camera or subject motion!
- Static photos must only be placed in the middle (the BUILD phase) to provide descriptive flavor/B-roll details, or as transitional highlights.

Good hooks:
- dramatic wide shots (Video)
- emotional atmosphere (Video)
- camera motion (Video)
- cinematic reveals (Video)
- visually striking imagery (Video)

Bad hooks:
- ANY static photo (Type: Static Photo) — NEVER use as the first clip!
- flat shots
- repetitive scenery
- weak handheld moments
- low-energy people shots

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
BUILD RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The middle should feel like progression.

Every next clip should:
- escalate emotion
- reveal new information
- OR create visual contrast

Alternate energy intelligently:
- wide ↔ close
- movement ↔ stillness
- human ↔ environment
- fast ↔ calm
- exterior ↔ detail

HARD RULE — NO CONSECUTIVE SAME TYPE:
NEVER place two clips of the same person or selfie back-to-back.
NEVER place two landscape/water/scenery clips back-to-back without a human clip between them.
If you have two selfie clips (same person facing camera), always put a scenery or action clip between them.
If you have two water/boat clips, always put a human moment between them.
This is non-negotiable — consecutive same-type clips kill pacing.

DO NOT place visually similar clips back-to-back.

The sequence should FEEL rhythmic.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
PAYOFF RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

The ending should feel emotionally satisfying.

The final clip should:
- feel memorable
- feel conclusive
- feel emotionally strongest
- OR leave lingering wonder

The strongest visual MAY appear:
- at the beginning
- in the middle
- OR at the end

Choose what creates the BEST overall reel.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TRANSITION RULES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

For the transitions between consecutive clips, apply specific editing logic:
- The Cross-Dissolve ("dissolve"): Use this ONLY as a bridge when transitioning from one "Act" to the next (e.g., from city architecture into the boat ride).
- The Zoom-In ("zoom_in" or "zoom_dissolve"): Use this INSIDE the Acts to emphasize exciting action (e.g., as someone hits the water/pool, or hits a table tennis ball).
- The Cut ("cut"): Use this as the default for cuts within the same location/scene to keep the pacing dynamic.
- The Fade ("fade"): Use this at the very start/end of the video. Do not use intermediate fades elsewhere.
- Set transition durations appropriately (e.g. 0.2s - 0.3s for fast action, 0.4s - 0.5s for slower dissolves/fades).

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
EDITORIAL THINKING
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Before finalizing, ask yourself:

- Which clip is the strongest opener?
- Which clips create contrast?
- Where does the reel breathe?
- Which shot feels like the emotional peak?
- Does the sequence feel cinematic?
- Would this retain viewers on Instagram/TikTok?
- Does every clip earn its place?

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON.

No markdown.
No explanations outside JSON.
No code fences.

{{
  "removed_clips": [
    {{
      "clip": 3,
      "reason": "visually repetitive and weaker than clip 7"
    }}
  ],

  "narrative_template": "State the overarching template you chose (e.g., 'Arrival to Departure', 'Day to Night', etc.)",

  "full_story": "2-3 sentence cinematic description of the emotional progression of the reel",

  "order": [4, 1, 0, 6, 2, 7, 5, 8], // MUST contain ALL {len(segments)} clip indices (0 to {len(segments)-1}). Do NOT skip any!

  "roles": [
    "hook",
    "build",
    "build",
    "build",
    "build",
    "build",
    "build",
    "payoff"
  ],

  "energy_flow": [
    "dramatic",
    "movement",
    "calm",
    "atmospheric",
    "steady",
    "curious",
    "intense",
    "epic"
  ],

  "transitions": [
    "fade",
    "zoom_dissolve",
    "dissolve",
    "cut",
    "zoom_in",
    "fade",
    "circle_crop"
  ], // Transition name between consecutive clips in order. Length MUST be exactly len(order) - 1. Choose mostly FLUID transitions: fade, dissolve, zoom_dissolve, zoom_in, zoom_out, circle_crop, cut. Avoid wipes/slides unless high-action.

  "transition_durations": [
    0.5,
    0.4,
    0.5,
    0.05,
    0.5,
    0.5,
    0.5
  ], // Duration of each transition in seconds. Length MUST be exactly len(order) - 1.

  "reasoning": "Explain why the hook works, why transitions feel emotionally effective, how contrast was used, why clips were removed, and why the ending feels satisfying."
}}

CRITICAL RULES:
- order and roles MUST be same length
- transitions and transition_durations MUST be of length (len(order) - 1)
- Choose mostly FLUID, organic transitions (fade, dissolve, zoom_dissolve, zoom_in, cut). Avoid wipes and slides unless representing continuous high-action sports footage (like pool action or ping pong play).
- no duplicate clips in order
- removed_clips MUST NOT appear in order
- You MUST include ALL clips in 'order' that you did not explicitly remove in 'removed_clips'. Do NOT drop clips silently.
- CLIP COUNT CHECK: There are {len(segments)} clips (indices 0 to {len(segments)-1}). Your 'order' array MUST contain exactly {len(segments)} minus len(removed_clips) indices. If you have 12 clips and removed 0, 'order' MUST have 12 entries.
- prioritize emotion over chronology
- prioritize pacing over documentation
- prioritize cinematic storytelling over logical sequencing
{directives_reminder}
{focus_constraint}
CRITICAL REASONING CONSTRAINT: Your thinking block (<think>...</think>) MUST be under 100 tokens. Summarize in 3 sentences max, then immediately output the JSON.
"""