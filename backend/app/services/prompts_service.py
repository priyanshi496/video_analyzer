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
        start = max(0.0, float(seg.get("start_sec", 0)))
        end   = min(float(duration), float(seg.get("end_sec", duration)))
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
) -> str:
    directives_note = ""
    if directives:
        directives_note = f"\nUSER EDITING DIRECTIVES (YOU MUST FOLLOW THESE INSTRUCTIONS):\n{directives}\n"

    if video_info.get("is_image"):
        return f"""You are a master short-form video editor. Analyze this static photo for a viral social reel.
{directives_note}
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
{directives_note}
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
- Each segment MUST be at least 2.0s to 5.0s long. STRICT MINIMUM: 2.0 seconds. Never extract a clip shorter than 2.0s unless the whole video is shorter than 2.0s. Approach/driving clips: max 3.0s.
- location_tag: snake_case label for the physical spot/subject (e.g. plane_interior, airport, car_interior, parking_lot, temple_entrance, temple_altar). Use the same tag for clips showing the same location/setting.
- journey_phase: approach|arrival|exterior|interior|detail|climax
- time_of_day: infer from lighting, sky color, shadows, and artificial light presence. dawn = soft pink/purple sky. morning = bright soft light, long shadows. afternoon = harsh overhead light. golden_hour = warm orange light, low sun. dusk = sky transitioning dark. night = dark sky, artificial lights dominant. If indoors with no sky visible, infer from light color temperature (warm tungsten = likely night, cool daylight = likely day).
- scene_category: Classify the dominant content of the clip. Options: scenery, people, action, food, vehicle, mixed.
- primary_subjects: List of 1-3 most visually prominent subjects (people by role/appearance like 'woman in yellow dress', objects, landmarks, landmarks like 'temple dome'). Be specific, not generic.
- Prefer 1–3 strong segments. Max 5. Stay within {duration}s.
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


def build_story_order_prompt(segments: list, all_results: list, directives: str = "", focus: dict = None, vibe_hint: str = "", transition_style: str = "") -> str:
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
            "reason": seg.get("reason", "")[:140],
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
Editor Read: {seg.get("editor_reasoning", "")[:220] or "N/A"}
""".strip()
        )

    # ─────────────────────────────────────────────────────────────
    # FINAL PROMPT
    # ─────────────────────────────────────────────────────────────

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
        directives_reminder = f"\n- CRITICAL: YOU MUST STRICTLY FOLLOW THESE USER EDITING DIRECTIVES:\n{directives}\n- WHATEVER THE USER MENTIONS IN THE DIRECTIVES MUST BE IMPLEMENTED IN THE VIDEO."
        loc_grouping_note = "Once all clips for one location finish playing, you move to the next location. Never go back to a previously finished location, EXCEPT when doing so is necessary to satisfy the USER EDITING DIRECTIVES (for instance, if the user explicitly asks to start and end with a plane/flight, or return to a location)."

    vibe_instructions = ""
    if vibe_hint:
        vibe_instructions = f"\nVIBE GUIDELINES:\n{vibe_hint}\n"
    if transition_style:
        vibe_instructions += f"Preferred transition style: {transition_style}. You MUST heavily favor this transition style between clips unless the pacing strictly requires a different cut.\n"

    focus_constraint = build_focus_constraint(focus)

    if directives:
        return f"""
You are an elite cinematic short-form video editor.

USER EDITING DIRECTIVES (YOU MUST FOLLOW THESE INSTRUCTIONS):
{directives}
{vibe_instructions}
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

Default action: KEEP the clip and find a good position for it. DO NOT completely exclude any source video unless instructed by the directives.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — BUILD THE ORDER BASED ON THE DIRECTIVES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

You have full freedom to reorder the clips to best satisfy the USER EDITING DIRECTIVES above.
Prioritize the chronological flow, subject focus, or progression requested by the user.
Ignore default location grouping, temporal flow, or strict hook rules if they contradict the user's explicit request.

- LOCATION GROUPING: Unless the USER EDITING DIRECTIVES explicitly ask to alternate/interleave locations, you MUST group clips from the same physical location/scene together as a contiguous block. Do NOT jump back and forth between completely different locations (e.g. birthday -> trampoline -> birthday) unless the directives explicitly demand that.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OUTPUT FORMAT
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Return ONLY valid JSON.
No markdown.
No explanations outside JSON.
No code fences.

{{
  "removed_clips": [],
  "full_story": "2-3 sentence cinematic description of the emotional progression of the reel",
  "order": [4, 1, 0, 6, 2, 7, 5, 8], // MUST contain ALL survived clip indices.
  "roles": ["hook", "build", "build", "build", "build", "build", "build", "payoff"],
  "energy_flow": ["dramatic", "movement", "calm", "atmospheric", "steady", "curious", "intense", "epic"],
  "transitions": [
    {{"from_index": 4, "to_index": 1, "type": "hard_cut", "duration": 0.0}},
    {{"from_index": 1, "to_index": 0, "type": "smooth_dissolve", "duration": 0.5}}
  ],
  "reasoning": "Explain how the sequence satisfies the USER EDITING DIRECTIVES."
}}

CRITICAL RULES:
- order and roles MUST be same length
- TRANSITION COUNT: The transitions array MUST have EXACTLY (len(order) - 1) items describing the transition between each clip. If your order array has N items, the transitions array MUST have N-1 items. Do NOT drop transitions.
- TRANSITION MENU: The `type` in the transitions array MUST be strictly chosen from this exact list: `hard_cut`, `fade`, `wipeleft`, `wiperight`, `slideleft`, `slideright`, `circlecrop`, `rectcrop`, `distance`, `dissolve`, `pixelize`, `radial`, `hblur`, `zoomin`, `fadeblack`. DO NOT invent transition names like `match_cut`.
- ACT LIKE A HUMAN EDITOR: Unless the USER EDITING DIRECTIVES explicitly request a specific transition style, roughly 50% of your transitions MUST be a 'hard_cut' (duration 0.0), and the other 50% MUST be dynamic transitions (like zoomin, wipeleft, fade). Use dynamic transitions to emphasize scene changes, beat drops, or major energy shifts. Set dynamic transition duration to 0.5.
- no duplicate clips in order
- removed_clips MUST NOT appear in order
- You MUST include ALL clips in 'order' that you did not explicitly remove in 'removed_clips'. Do NOT drop clips silently.
- CLIP COUNT CHECK: There are {len(segments)} clips (indices 0 to {len(segments)-1}). Your 'order' array MUST contain exactly {len(segments)} minus len(removed_clips) indices.
- LOCATION GROUPING: Unless explicitly requested by the user's directives, you MUST group clips from the same physical location/scene together contiguously. Do NOT alternate or interleave locations.
- CRITICAL: YOU MUST STRICTLY FOLLOW THESE USER EDITING DIRECTIVES:
{directives}

CRITICAL REASONING CONSTRAINT: Your thinking block (<think>...</think>) MUST be under 100 tokens. Summarize in 3 sentences max, then immediately output the JSON.
"""

    return f"""
You are an elite cinematic short-form video editor.
{directives_note}
{vibe_instructions}
CRITICAL INSTRUCTION FOR REASONING AND THINKING:
Keep your internal thinking process (the reasoning path before outputting JSON) extremely short, concise, and direct (maximum 3-4 sentences total). Do not write long explanations, nested logic, or repetitive drafts. Summarize your thoughts immediately and output the final JSON object.

You are editing a premium Instagram/TikTok travel reel from raw trip footage.

Your goal is to build a cohesive, connected story.

Think like a real editor:
- viewer retention first
- logical story connections first
- chronological sequencing where it makes sense
- clear and cohesive journey

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
start of journey → building the experience → main highlight → satisfying conclusion

You are organizing clips to tell a coherent story.

You are crafting a clear, logical sequence.

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

Be VERY conservative about removal. Removing a good clip is worse than keeping one extra clip.

You MUST NOT remove a clip unless BOTH of these are true:
1. It shows the EXACT SAME framing AND subject as another clip already in the reel
2. The other version is clearly stronger (better blur/shake scores or more decisive action)

Do NOT remove clips because:
- they show a similar location (different framing = different clip)
- they feel "less cinematic" but are visually fine
- you are trying to keep the reel short
- they show the same person in a different moment or expression

DO NOT completely exclude any source video from the final reel. Every source video must contribute at least one clip.

Only remove if you cannot use the clip without making the sequence feel repetitive (e.g. two shots of identical framing of the same subject with the same expression).

Default action: KEEP the clip and find a good position for it.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 — BUILD THE EMOTIONAL ARC
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

{temporal_note}

Your job is ONLY to:
1. Decide the best HOOK (first clip) within the first time block.
2. Ensure no consecutive same-type clips (swap adjacent clips if needed).
3. Choose the best PAYOFF (final clip).
4. LOCATION GROUPING: Clips from the same physical location MUST be strictly grouped together as a contiguous block. Do NOT interleave clips from different locations. Note that different clips might have slightly different location names from individual analysis; you must group similar tags (or tags representing the same physical venue/activity) as the same location. {loc_grouping_note}

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
    {{"from_index": 4, "to_index": 1, "type": "hard_cut", "duration": 0.0}},
    {{"from_index": 1, "to_index": 0, "type": "smooth_dissolve", "duration": 0.5}}
  ],

  "reasoning": "Explain why the hook works, why transitions feel emotionally effective, how contrast was used, why clips were removed, and why the ending feels satisfying."
}}

CRITICAL RULES:
- order and roles MUST be same length
- TRANSITION COUNT: The transitions array MUST have EXACTLY (len(order) - 1) items describing the transition between each clip. If your order array has N items, the transitions array MUST have N-1 items. Do NOT drop transitions.
- TRANSITION MENU: The `type` in the transitions array MUST be strictly chosen from this exact list: `hard_cut`, `fade`, `wipeleft`, `wiperight`, `slideleft`, `slideright`, `circlecrop`, `rectcrop`, `distance`, `dissolve`, `pixelize`, `radial`, `hblur`, `zoomin`, `fadeblack`. DO NOT invent transition names like `match_cut`.
- ACT LIKE A HUMAN EDITOR: Unless the USER EDITING DIRECTIVES explicitly request a specific transition style, roughly 50% of your transitions MUST be a 'hard_cut' (duration 0.0), and the other 50% MUST be dynamic transitions (like zoomin, wipeleft, fade). Use dynamic transitions to emphasize scene changes, beat drops, or major energy shifts. Set dynamic transition duration to 0.5.
- no duplicate clips in order
- removed_clips MUST NOT appear in order
- You MUST include ALL clips in 'order' that you did not explicitly remove in 'removed_clips'. Do NOT drop clips silently.
- CLIP COUNT CHECK: There are {len(segments)} clips (indices 0 to {len(segments)-1}). Your 'order' array MUST contain exactly {len(segments)} minus len(removed_clips) indices. If you have 12 clips and removed 0, 'order' MUST have 12 entries.
- prioritize logical story connections (connecting the dots) so the video makes sense from beginning to end
- prioritize a cohesive chronological journey over pure emotional pacing
- prioritize clear, logical sequencing while still keeping it engaging
{directives_reminder}
{focus_constraint}
CRITICAL REASONING CONSTRAINT: Your thinking block (<think>...</think>) MUST be under 100 tokens. Summarize in 3 sentences max, then immediately output the JSON.
"""