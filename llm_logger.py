"""
llm_logger.py — Logs every LLM prompt (input) and raw response (output) to disk.

Creates one file per run in logs/llm/<timestamp>/
  vision_<video_stem>_attempt<N>.txt  — Nemotron vision calls
  story_order_attempt<N>.txt          — GPT-OSS story ordering call

Each file contains:
  [OUTPUT] — the raw text the model returned (before JSON parsing)
  [PARSED] — the parsed JSON (or the parse error)
  [META]   — model name, duration, token estimate, timestamp
"""

import json
import logging
import time
from datetime import datetime
from pathlib import Path


# ── Setup ─────────────────────────────────────────────────────────────────────

_run_dir: Path | None = None


def init_run_log_dir(base: str = "logs/llm") -> Path:
    """
    Call once at the start of each pipeline run.
    Creates logs/llm/YYYYMMDD_HHMMSS/ and returns the path.
    """
    global _run_dir
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    _run_dir = Path(base) / ts
    _run_dir.mkdir(parents=True, exist_ok=True)
    logging.info(f"  [llm_logger] Logging LLM calls → {_run_dir}/")
    return _run_dir


def _get_run_dir() -> Path:
    if _run_dir is None:
        # Fallback if init was never called
        return init_run_log_dir()
    return _run_dir


def _estimate_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token."""
    return len(text) // 4


# ── Core Logger ───────────────────────────────────────────────────────────────

def log_llm_call(
    label: str,          # e.g. "vision_WhatsApp_Video_01" or "story_order"
    model: str,          # e.g. "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
    prompt: str,         # full prompt text sent to model
    raw_response: str,   # raw text returned by model (before parsing)
    parsed: dict | None, # parsed JSON dict, or None if parsing failed
    parse_error: str | None = None,  # error message if parsing failed
    attempt: int = 1,    # retry attempt number
    duration_sec: float = 0.0,
) -> Path:
    """
    Write a single LLM call log file.
    Returns the path to the written file.
    """
    run_dir = _get_run_dir()

    # Sanitize label for filename
    safe_label = label.replace("/", "_").replace(" ", "_")[:80]
    filename   = f"{safe_label}_attempt{attempt}.txt"
    filepath   = run_dir / filename

    input_tokens  = _estimate_tokens(prompt)
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

    # Automatically append clip index mapping for story ordering for easy reference at the bottom
    if label == "story_order":
        try:
            start_marker = "AVAILABLE CLIPS"
            end_marker = "STEP 1"
            if start_marker in prompt and end_marker in prompt:
                clips_part = prompt.split(start_marker)[1].split(end_marker)[0].strip()
                # Clean up horizontal dividers
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

    filepath.write_text("\n".join(sections), encoding="utf-8")

    # Also emit a short summary to the main console log
    status = "✓" if parsed else "✗"
    logging.info(
        f"  [llm_logger] {status} {label} | {model.split('/')[-1]} | "
        f"{duration_sec:.1f}s | ~{input_tokens}in/{output_tokens}out tokens | "
        f"→ {filepath.name}"
    )

    return filepath


# ── Convenience Wrappers ──────────────────────────────────────────────────────

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
) -> Path:
    """Log a Nemotron vision analysis call."""
    stem  = Path(video_path).stem[:40]
    label = f"vision_{stem}_{chunk_label}" if chunk_label else f"vision_{stem}"
    return log_llm_call(
        label=label,
        model=model,
        prompt=prompt,
        raw_response=raw_response,
        parsed=parsed,
        parse_error=parse_error,
        attempt=attempt,
        duration_sec=duration_sec,
    )


def log_story_order_call(
    model: str,
    prompt: str,
    raw_response: str,
    parsed: dict | None,
    parse_error: str | None = None,
    attempt: int = 1,
    duration_sec: float = 0.0,
) -> Path:
    """Log a GPT-OSS story ordering call."""
    return log_llm_call(
        label="story_order",
        model=model,
        prompt=prompt,
        raw_response=raw_response,
        parsed=parsed,
        parse_error=parse_error,
        attempt=attempt,
        duration_sec=duration_sec,
    )


# ── Run Summary ───────────────────────────────────────────────────────────────

def write_run_summary(
    all_results: list,
    final_segments: list,
    story_order: list | None,
    total_duration_sec: float,
) -> Path:
    """
    Write a human-readable summary of the full pipeline run.
    Call this at the very end of pipeline execution.
    """
    run_dir = _get_run_dir()
    filepath = run_dir / "SUMMARY.txt"

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
        from llm import get_api_metrics, token_tracker
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

    lines += [
        "━━━ PER-VIDEO RESULTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]

    for r in all_results:
        stem     = Path(r.get("video_path", "?")).stem
        analysis = r.get("analysis", {})
        segs     = analysis.get("best_segments", [])
        scenario = analysis.get("detected_scenario", "?")
        mood     = analysis.get("overall_mood", "")
        reasoning = analysis.get("editor_reasoning", "")[:200]

        lines.append(f"  {stem}")
        lines.append(f"    scenario : {scenario} | mood: {mood}")
        lines.append(f"    editor   : {reasoning}")
        lines.append(f"    segments :")
        for s in segs:
            loc   = s.get("location_tag",  "?")
            phase = s.get("journey_phase", "?")
            start = s.get("start_sec", 0)
            end   = s.get("end_sec",   0)
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
        loc   = seg.get("location_tag",  "?")
        phase = seg.get("journey_phase", "?")
        role  = seg.get("story_role", seg.get("narrative_role", "?"))
        start = seg.get("start_sec", 0)
        end   = seg.get("end_sec",   0)
        src   = Path(seg.get("video_path", "?")).stem
        lines.append(f"  [{i:02d}] {role:8s} | {phase:10s} | {loc:30s} | {start}s–{end}s | {src}")

    if unused_segs:
        lines += [
            "",
            "━━━ UNUSED / CUTTING ROOM FLOOR ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            f"  ({len(unused_segs)} clips not included in reel)",
            "",
        ]
        for i, seg in enumerate(unused_segs):
            loc   = seg.get("location_tag",  "?")
            phase = seg.get("journey_phase", "?")
            role  = seg.get("narrative_role", "?")
            start = seg.get("start_sec", 0)
            end   = seg.get("end_sec",   0)
            src   = Path(seg.get("video_path", "?")).stem
            lines.append(f"  [--] {role:8s} | {phase:10s} | {loc:30s} | {start}s–{end}s | {src}")

    lines += ["", divider]
    filepath.write_text("\n".join(lines), encoding="utf-8")
    logging.info(f"  [llm_logger] Run summary → {filepath}")
    return filepath
