import json
import logging
import time
from datetime import datetime
from pathlib import Path

from app.services.storage_service import storage_service

_run_id: str | None = None

def init_run_log_dir(job_id: str) -> str:
    global _run_id
    _run_id = job_id
    logging.info(f"  [logger_service] Logging LLM calls to MinIO under logs/llm/{_run_id}/")
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
    parsed: dict | None,
    parse_error: str | None = None,
    attempt: int = 1,
    duration_sec: float = 0.0,
) -> str:
    run_id = _get_run_id()
    safe_label = label.replace("/", "_").replace(" ", "_")[:80]
    filename = f"{safe_label}_attempt{attempt}.md"
    object_key = f"logs/llm/{run_id}/{filename}"

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
    
    # Upload to MinIO
    storage_service.upload_log_text(md_content, object_key)

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
    parsed: dict | None,
    parse_error: str | None = None,
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
    parsed: dict | None,
    parse_error: str | None = None,
    attempt: int = 1,
    duration_sec: float = 0.0,
) -> str:
    return log_llm_call("story_order", model, prompt, raw_response, parsed, parse_error, attempt, duration_sec)

def write_run_summary(
    all_results: list,
    final_segments: list,
    story_order: list | None,
    total_duration_sec: float,
) -> str:
    run_id = _get_run_id()
    object_key = f"logs/llm/{run_id}/SUMMARY.md"

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
        f"Story order: {story_order}",
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
    storage_service.upload_log_text(md_content, object_key)
    logging.info(f"  [logger_service] Run summary → {object_key}")
    return object_key
