from __future__ import annotations
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.services.storage_service import storage_service

_run_id: Optional[str] = None

def init_run_log_dir(project_id: str, job_id: str) -> str:
    global _run_id
    _run_id = f"{project_id}/{job_id}"
    Path(f"logs/{_run_id}").mkdir(parents=True, exist_ok=True)
    logging.info(f"  [logger_service] Logging LLM calls locally under logs/{_run_id}/")
    return _run_id

def _get_run_id() -> str:
    if _run_id is None:
        return "unknown_job"
    return _run_id

def _estimate_tokens(text: str) -> int:
    return len(text) // 4

def log_llm_call(
    label: str,
    model: str,
    prompt: str,
    raw_response: str,
    parsed: Optional[dict],
    parse_error: Optional[str] = None,
    attempt: int = 1,
    duration_sec: float = 0.0,
) -> str:
    run_id = _get_run_id()
    safe_label = label.replace("/", "_").replace(" ", "_")[:80]
    filename = f"{safe_label}_attempt{attempt}.md"
    object_key = f"logs/{run_id}/{filename}"

    input_tokens = _estimate_tokens(prompt)
    output_tokens = _estimate_tokens(raw_response or "")

    divider = "═" * 80
    sections = [
        f"{divider}",
        f"  LLM CALL LOG",
        f"  label   : {label}",
        f"  model   : {model}",
        f"  attempt : {attempt}",
        f"  duration: {duration_sec:.1f}s",
        f"  tokens  : ~{input_tokens} input / ~{output_tokens} output",
        f"  time    : {datetime.now().isoformat()}",
        f"{divider}",
        "",
        "━━━ INPUT PROMPT ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        prompt,
        "",
        "━━━ OUTPUT (raw model response) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        raw_response or "(empty / no response)",
        "",
    ]

    if parse_error:
        sections += [
            "━━━ PARSE RESULT: ✗ FAILED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"ERROR: {parse_error}",
            "",
        ]
    elif parsed is not None:
        sections += [
            "━━━ PARSE RESULT: ✓ SUCCESS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            json.dumps(parsed, indent=2, ensure_ascii=False),
            "",
        ]

    if label == "story_order":
        try:
            start_marker = "AVAILABLE CLIPS"
            end_marker = "STEP 1"
            if start_marker in prompt and end_marker in prompt:
                clips_part = prompt.split(start_marker)[1].split(end_marker)[0].strip()
                lines = [line.strip() for line in clips_part.split("\n")]
                lines = [line for line in lines if not all(c in "━ \r\n" for c in line)]
                clips_part = "\n".join(lines).strip()
                if clips_part:
                    sections += [
                        "━━━ CLIPS INDEX MAPPING (FOR EASY REFERENCE) ━━━━━━━━━━━━━━━━━━━━━━",
                        "",
                        clips_part,
                        "",
                    ]
        except Exception as e:
            logging.warning(f"Failed to append clip index mapping to log: {e}")

    sections.append(divider)
    text_content = "\n".join(sections)
    
    # Wrap in markdown code block for clean preview
    md_content = f"```text\n{text_content}\n```"
    
    # Save locally
    log_file_path = Path(object_key)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    status = "✓" if parsed else "✗"
    logging.info(
        f"  [logger_service] {status} {label} | {model.split('/')[-1]} | "
        f"{duration_sec:.1f}s | ~{input_tokens}in/{output_tokens}out tokens | "
        f"→ {object_key}"
    )

    return object_key

def log_vision_call(
    video_path: str,
    model: str,
    prompt: str,
    raw_response: str,
    parsed: Optional[dict],
    parse_error: Optional[str] = None,
    attempt: int = 1,
    duration_sec: float = 0.0,
    chunk_label: str = "",
) -> str:
    stem  = Path(video_path).stem[:40]
    label = f"vision_{stem}_{chunk_label}" if chunk_label else f"vision_{stem}"
    return log_llm_call(label, model, prompt, raw_response, parsed, parse_error, attempt, duration_sec)

def log_story_order_call(
    model: str,
    prompt: str,
    raw_response: str,
    parsed: Optional[dict],
    parse_error: Optional[str] = None,
    attempt: int = 1,
    duration_sec: float = 0.0,
) -> str:
    return log_llm_call("story_order", model, prompt, raw_response, parsed, parse_error, attempt, duration_sec)

def write_run_summary(
    all_results: list,
    final_segments: list,
    story_parsed: Optional[dict],
    total_duration_sec: float,
) -> str:
    run_id = _get_run_id()
    object_key = f"logs/{run_id}/SUMMARY.md"

    divider = "═" * 80
    lines = [
        divider,
        "  PIPELINE RUN SUMMARY",
        f"  time    : {datetime.now().isoformat()}",
        f"  duration: {total_duration_sec:.1f}s total",
        divider,
        "",
        f"Videos analyzed: {len(all_results)}",
        f"Best segments selected: {len(final_segments)}",
        f"Story order: {story_parsed.get('order') if story_parsed else None}",
        f"Story reasoning: {story_parsed.get('reasoning') if story_parsed else 'N/A'}",
        f"Audio reasoning: {story_parsed.get('audio_reasoning') if story_parsed else 'N/A'}",
        "",
    ]

    try:
        from app.services.llm_service import get_api_metrics, token_tracker
        metrics = get_api_metrics()
        tokens = token_tracker.get_total_usage()
        
        lines += [
            "━━━ API HEALTH & TOKEN METRICS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"  NVIDIA NIM Retries        : {metrics.get('nim_retries', 0)}",
            f"  OpenRouter Fallback Calls : {metrics.get('openrouter_fallbacks', 0)}",
            f"  NVIDIA Circuit Broken     : {metrics.get('nvidia_circuit_broken', False)}",
            f"  Accumulated Input Tokens  : {tokens.get('input_tokens', 0)}",
            f"  Accumulated Output Tokens : {tokens.get('output_tokens', 0)}",
            f"  Accumulated Total Tokens  : {tokens.get('total', 0)}",
            "",
        ]
    except Exception as e:
        logging.warning(f"Failed to append API metrics to run summary: {e}")

    lines += ["━━━ PER-VIDEO RESULTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━", ""]

    for r in all_results:
        stem = Path(r.get("video_path", "?")).stem
        analysis = r.get("analysis", {})
        segs = analysis.get("best_segments", [])
        scenario = analysis.get("detected_scenario", "?")
        mood = analysis.get("overall_mood", "")
        reasoning = analysis.get("editor_reasoning", "")[:200]

        lines.append(f"  {stem}")
        lines.append(f"    scenario : {scenario} | mood: {mood}")
        lines.append(f"    editor   : {reasoning}")
        lines.append(f"    segments :")
        for s in segs:
            loc = s.get("location_tag", "?")
            phase = s.get("journey_phase", "?")
            start = s.get("start_sec", 0)
            end = s.get("end_sec", 0)
            lines.append(f"      [{start}s–{end}s] {loc} ({phase}) — {s.get('reason','')[:80]}")
        lines.append("")

    active_segs = [seg for seg in final_segments if seg.get("is_used", False)]
    unused_segs = [seg for seg in final_segments if not seg.get("is_used", False)]

    lines += [
        "━━━ ACTIVE REEL SEQUENCE ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  ({len(active_segs)} clips in the final reel)",
        "",
    ]
    for i, seg in enumerate(active_segs):
        loc = seg.get("location_tag", "?")
        phase = seg.get("journey_phase", "?")
        role = seg.get("story_role", seg.get("narrative_role", "?"))
        start = seg.get("start_sec", 0)
        end = seg.get("end_sec", 0)
        src = Path(seg.get("video_path", "?")).stem
        lines.append(f"  [{i:02d}] {role:8s} | {phase:10s} | {loc:30s} | {start}s–{end}s | {src}")

    if unused_segs:
        lines += [
            "",
            "━━━ UNUSED / CUTTING ROOM FLOOR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  ({len(unused_segs)} clips not included in reel)",
            "",
        ]
        for i, seg in enumerate(unused_segs):
            loc = seg.get("location_tag", "?")
            phase = seg.get("journey_phase", "?")
            role = seg.get("narrative_role", "?")
            start = seg.get("start_sec", 0)
            end = seg.get("end_sec", 0)
            src = Path(seg.get("video_path", "?")).stem
            lines.append(f"  [--] {role:8s} | {phase:10s} | {loc:30s} | {start}s–{end}s | {src}")

    lines += ["", divider]
    text_content = "\n".join(lines)
    
    md_content = f"```text\n{text_content}\n```"
    
    log_file_path = Path(object_key)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write(md_content)
        
    logging.info(f"  [logger_service] Run summary → {object_key}")
    return object_key


def write_beat_sync_log(
    bgm_path: str,
    bgm_start_sec: float,
    raw_hook_sec: float,
    chosen_hook: Optional[dict],
    all_hooks: list,
    energy_map: list,
    tempo_bpm: float,
    beat_times: list,
    snapped_segments: list,
) -> str:
    """
    Write a dedicated BEATSYNC.md log explaining:
      - Which audio hook was chosen and WHY
      - The full energy map of the track
      - Every clip's beat-snap decision (which beat, how much it moved)
    """
    run_id = _get_run_id()
    object_key = f"logs/{run_id}/BEATSYNC.md"

    divider = "═" * 80
    lines = [
        divider,
        "  🎵  BEAT SYNC ANALYSIS LOG",
        f"  time    : {datetime.now().isoformat()}",
        f"  file    : {Path(bgm_path).name}",
        f"  tempo   : {tempo_bpm:.1f} BPM",
        divider,
        "",
        "━━━ HOOK SELECTION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  Raw hook timestamp from LLM  : {raw_hook_sec:.3f}s",
        f"  Snapped to nearest beat       : {bgm_start_sec:.3f}s",
        f"  BGM audio will start at       : {bgm_start_sec:.3f}s (skipping the intro)",
        "",
    ]

    if chosen_hook:
        lines += [
            "  Selected hook details:",
            f"    type           : {chosen_hook.get('hook_type', 'N/A')}",
            f"    energy_level   : {chosen_hook.get('energy_level', 'N/A')}",
            f"    start_sec      : {chosen_hook.get('start_sec', 'N/A')}s",
            f"    end_sec        : {chosen_hook.get('end_sec', 'N/A')}s",
            f"    editing note   : {chosen_hook.get('editing_instruction', 'N/A')}",
            "",
            "  Why this hook?",
            "    The LLM scans the audio energy map and picks the first 'high' energy segment.",
            "    Starting the music here puts the viewer immediately in a high-energy moment",
            "    (chorus / drop) instead of sitting through a slow intro.",
        ]
    
    lines += [
        "",
        "━━━ ALL HOOKS DETECTED IN TRACK ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  {'#':>3}  {'Type':12}  {'Energy':8}  {'Start':>8}  {'End':>8}  Editing Instruction",
        f"  {'─'*3}  {'─'*12}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*40}",
    ]
    for i, h in enumerate(all_hooks):
        chosen_marker = " ◄ CHOSEN" if h is chosen_hook or (chosen_hook and h.get('start_sec') == chosen_hook.get('start_sec')) else ""
        lines.append(
            f"  {i+1:>3}  {h.get('hook_type','?'):12}  "
            f"{h.get('energy_level','?'):8}  "
            f"{h.get('start_sec',0):>7.1f}s  "
            f"{h.get('end_sec',0):>7.1f}s  "
            f"{h.get('editing_instruction','')[:40]}{chosen_marker}"
        )
    
    lines += [
        "",
        "━━━ AUDIO ENERGY MAP ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  {'#':>3}  {'Start':>8}  {'End':>8}  {'Score':>6}  {'Bar':30}  Category",
        f"  {'─'*3}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*30}  {'─'*30}",
    ]
    for i, e in enumerate(energy_map):
        score = e.get('energy_score', 0)
        bar_len = int((score / 10.0) * 30)
        bar = '█' * bar_len + '░' * (30 - bar_len)
        lines.append(
            f"  {i+1:>3}  {e.get('start_sec',0):>7.1f}s  {e.get('end_sec',0):>7.1f}s  "
            f"{score:>6.1f}  {bar}  {e.get('description','')[:30]}"
        )

    lines += [
        "",
        "━━━ BEAT TIMES (first 30 beats, after hook offset) ━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    relevant_beats = [b for b in beat_times if b >= bgm_start_sec][:30]
    beat_line = "  " + "  ".join(f"{b:.3f}s" for b in relevant_beats)
    lines.append(beat_line)

    lines += [
        "",
        "━━━ BEAT WINDOW → CLIP MAPPING ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  {'Pos':>3}  {'Window (Beat Times)':>22}  {'Dur':>5}  {'Clip Source':>20}  {'Seg Time':>15}  {'LLM Beat Reason'}",
        f"  {'─'*3}  {'─'*22}  {'─'*5}  {'─'*20}  {'─'*15}  {'─'*30}",
    ]
    for i, seg in enumerate(snapped_segments):
        if not seg.get('is_used', True):
            continue
        
        src = Path(seg.get('video_path', '?')).stem[:20]
        orig_start = seg.get('start_sec', 0)
        orig_end = seg.get('end_sec', 0)
        win_start = seg.get('_beat_window_start')
        win_end = seg.get('_beat_window_end')
        reason = str(seg.get('story_role', ''))[:40] # story_role holds the assigned reason
        
        if win_start is not None and win_end is not None:
            win_str = f"{win_start:.3f}s → {win_end:.3f}s"
            dur_str = f"{(win_end - win_start):.2f}s"
        else:
            win_str = "Legacy Snap Fallback"
            dur_str = f"{(orig_end - orig_start):.2f}s"
            
        seg_time = f"{orig_start:.2f}s–{orig_end:.2f}s"
        
        lines.append(
            f"  {i:>3}  {win_str:>22}  {dur_str:>5}  {src:>20}  {seg_time:>15}  {reason}"
        )

    lines += ["", divider]
    text_content = "\n".join(lines)
    md_content = f"```text\n{text_content}\n```"

    log_file_path = Path(object_key)
    log_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file_path, "w", encoding="utf-8") as f:
        f.write(md_content)

    logging.info(f"  [logger_service] Beat sync log → {object_key}")
    return object_key
