#!/usr/bin/env python3
"""
beat_sync/generate_beat_log.py
───────────────────────────────────────────────────────────────────────────────
Standalone script: analyze a music file with librosa, save a detailed
BEAT_ANALYSIS_<name>.md log into backend/logs/.

Usage:
  python3 beat_sync/generate_beat_log.py                        # uses default BGM_PATH
  python3 beat_sync/generate_beat_log.py /path/to/track.mp3    # custom file
───────────────────────────────────────────────────────────────────────────────
"""

import sys
import os
from pathlib import Path

# Make sure root is on path so beat_sync imports work
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "beat_sync"))
sys.path.insert(0, str(ROOT / "backend"))

# Load .env so API keys are available when running standalone
env_file = ROOT / "backend" / ".env"
if env_file.exists():
    from dotenv import load_dotenv
    load_dotenv(env_file)

from beat_sync.audio_analyzer import analyze_bgm, extract_audio_energy_map, analyze_audio_hooks_with_llm

def main():
    if len(sys.argv) > 1:
        song_path = sys.argv[1]
    else:
        from beat_sync.config import BGM_PATH
        song_path = BGM_PATH

    song_path = str(Path(song_path).resolve())
    song_name = Path(song_path).name
    safe_name = Path(song_path).stem.replace(" ", "_").replace("(", "").replace(")", "")

    print(f"\n🎵 Analyzing: {song_name}")
    print("  Loading audio + extracting beats via librosa...")
    bm = analyze_bgm(song_path, verbose=False)
    print(f"  ✓ {bm.tempo_bpm:.1f} BPM  |  {len(bm.beat_times)} beats  |  {bm.total_duration_sec:.1f}s total")

    print("  Extracting energy map (15 bins)...")
    em = extract_audio_energy_map(song_path, num_bins=15)
    print("  ✓ Energy map ready")

    print("  Calling Nemotron to identify hooks...")
    try:
        hooks_data = analyze_audio_hooks_with_llm(song_name, bm.tempo_bpm, bm.total_duration_sec, em)
        all_hooks = hooks_data.get("hooks", [])
        chosen_hook = next((h for h in all_hooks if h.get("energy_level") == "high"), all_hooks[0] if all_hooks else None)
        music_summary = hooks_data.get("music_summary", "N/A")
        vibe = hooks_data.get("vibe_recommendation", "N/A")
    except Exception as e:
        print(f"  ⚠️  LLM hook analysis failed ({e}) — falling back to rule-based hooks")
        all_hooks = [e for e in em if e.get("energy_score", 0) >= 7.5]
        chosen_hook = all_hooks[0] if all_hooks else None
        music_summary = "Could not determine (LLM unavailable)"
        vibe = "N/A"

    # ── Snap chosen hook to nearest beat ─────────────────────────────────────
    if chosen_hook:
        raw_hook_sec = float(chosen_hook.get("start_sec", 0.0))
        snapped_hook_sec = min(bm.beat_times, key=lambda b: abs(b - raw_hook_sec))
    else:
        raw_hook_sec = 0.0
        snapped_hook_sec = bm.beat_times[0] if bm.beat_times else 0.0

    # ── Build the log file ────────────────────────────────────────────────────
    divider = "═" * 80
    thin    = "─" * 80

    lines = [
        "```text",
        divider,
        "  🎵  BEAT ANALYSIS LOG",
        f"  file    : {song_name}",
        f"  tempo   : {bm.tempo_bpm:.1f} BPM",
        f"  duration: {bm.total_duration_sec:.1f}s",
        f"  beats   : {len(bm.beat_times)} total",
        divider,
        "",
        "━━━ MUSIC SUMMARY (from Nemotron) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  Style / rhythm : {music_summary}",
        f"  Best vibe for  : {vibe}",
        "",
        "━━━ HOOK SELECTION ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  Chosen hook (raw LLM timestamp) : {raw_hook_sec:.3f}s",
        f"  Snapped to nearest beat          : {snapped_hook_sec:.3f}s",
        f"  Audio playback starts at         : {snapped_hook_sec:.3f}s",
        "",
    ]

    if chosen_hook:
        lines += [
            "  Hook details:",
            f"    type         : {chosen_hook.get('hook_type', 'N/A')}",
            f"    energy_level : {chosen_hook.get('energy_level', 'N/A')}",
            f"    window       : {chosen_hook.get('start_sec', '?')}s → {chosen_hook.get('end_sec', '?')}s",
            f"    editing note : {chosen_hook.get('editing_instruction', 'N/A')}",
        ]

    lines += [
        "",
        "━━━ ALL HOOKS DETECTED ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  {'#':>3}  {'Type':12}  {'Energy':8}  {'Start':>8}  {'End':>8}  Editing Instruction",
        f"  {'─'*3}  {'─'*12}  {'─'*8}  {'─'*8}  {'─'*8}  {'─'*40}",
    ]
    for i, h in enumerate(all_hooks):
        marker = "  ◄ CHOSEN" if chosen_hook and h.get("start_sec") == chosen_hook.get("start_sec") else ""
        lines.append(
            f"  {i+1:>3}  {h.get('hook_type','?'):12}  "
            f"{h.get('energy_level','?'):8}  "
            f"{h.get('start_sec', 0):>7.1f}s  "
            f"{h.get('end_sec', 0):>7.1f}s  "
            f"{h.get('editing_instruction','')[:40]}{marker}"
        )

    lines += [
        "",
        "━━━ AUDIO ENERGY MAP (15 time bins) ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  {'#':>3}  {'Start':>8}  {'End':>8}  {'Score':>6}  {'Energy Bar':30}  Category",
        f"  {'─'*3}  {'─'*8}  {'─'*8}  {'─'*6}  {'─'*30}  {'─'*32}",
    ]
    for i, e in enumerate(em):
        score = e.get("energy_score", 0)
        bar_len = int((score / 10.0) * 30)
        bar = "█" * bar_len + "░" * (30 - bar_len)
        star = "  ◄ HIGH ENERGY (HOOK ZONE)" if score >= 7.5 else ""
        lines.append(
            f"  {i+1:>3}  {e.get('start_sec',0):>7.1f}s  {e.get('end_sec',0):>7.1f}s  "
            f"{score:>6.1f}  [{bar}]  {e.get('description','')[:32]}{star}"
        )

    lines += [
        "",
        f"━━━ ALL {len(bm.beat_times)} BEAT TIMESTAMPS @ {bm.tempo_bpm:.1f} BPM ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    beats = bm.beat_times
    for row_start in range(0, len(beats), 8):
        row = beats[row_start:row_start + 8]
        row_label = f"  [{row_start:>3}]"
        beat_str = "  ".join(f"{b:>8.4f}s" for b in row)
        lines.append(f"{row_label}  {beat_str}")

    lines += ["", divider, "```"]

    # ── Save ──────────────────────────────────────────────────────────────────
    out_dir = ROOT / "backend" / "logs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"BEAT_ANALYSIS_{safe_name}.md"
    out_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"\n✅  Log saved to:\n   {out_path}")
    print(f"\n📊 Quick Summary:")
    print(f"   BPM          : {bm.tempo_bpm:.1f}")
    print(f"   Total beats  : {len(bm.beat_times)}")
    print(f"   Duration     : {bm.total_duration_sec:.1f}s")
    print(f"   Hook starts  : {snapped_hook_sec:.3f}s  (raw: {raw_hook_sec:.3f}s)")
    print(f"   High-energy  : {sum(1 for e in em if e.get('energy_score',0) >= 7.5)} / {len(em)} bins")


if __name__ == "__main__":
    main()
