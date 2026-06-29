"""
universal_renderer.py
─────────────────────
One renderer to rule all templates.

Every template is a JSON file with a "tracks" array.
This file reads that array and builds the FFmpeg filtergraph dynamically.
No new Python needed for new templates — just drop a JSON file.

Supported track types:
  - video   : places a clip at x,y,w,h between start and end seconds
  - text    : draws text overlay with optional slide_up / fade animation

Supported transition_in types (per video track):
  - cut     : appears instantly (default)
  - fade    : fades in over transition_in.duration seconds
  - slam    : brightness flash on first 0.07s (cheap punch feel)
              use transition_in.delay to stagger multiple cells

Called from pipeline_service.py:
  from app.services.universal_renderer import render_universal_template
  render_universal_template(clip_paths, output_path, template)
"""

import os
import subprocess
import logging
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

def _drawtext_available() -> bool:
    try:
        result = subprocess.run(
            ["ffmpeg", "-filters"], capture_output=True, text=True
        )
        return "drawtext" in result.stdout
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def render_universal_template(
    clip_paths: dict,   # { "slot_1": "/tmp/clip_01.mp4", ... }
    output_path: str,
    template: dict,     # full parsed template JSON
) -> str:
    """
    Renders the template and writes the result to output_path.
    Returns output_path.
    """
    canvas      = template.get("canvas", {"w": 1080, "h": 1920, "fps": 30})
    W           = canvas.get("w",   1080)
    H           = canvas.get("h",   1920)
    FPS         = canvas.get("fps", 30)
    total_dur   = float(template["total_duration"])
    tracks      = template["tracks"]

    video_tracks = [t for t in tracks if t["type"] == "video"]
    text_tracks  = [t for t in tracks if t["type"] == "text"]

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)

        # ── 1. Normalize every unique slot clip ───────────────────────────
        normed = {}
        for slot_id, src in clip_paths.items():
            dst = tmp / f"norm_{slot_id}.mp4"
            _normalize(src, str(dst), W, H, FPS)
            normed[slot_id] = str(dst)

        # ── 2. Build FFmpeg inputs list + per-clip filter chains ──────────
        #
        # Each video track gets:
        #   trim → setpts → scale → crop → [optional brightness flash] → label
        #
        # We allow the same slot_id to appear in multiple tracks
        # (e.g. same clip shown in two cells simultaneously).
        # FFmpeg can't share an input stream between two filter chains,
        # so we open the file once per track (not per unique slot).

        ff_inputs     = []   # flat list fed to ffmpeg -i flags
        filter_parts  = []   # individual filter chain strings
        input_index   = 0    # increments per track (not per slot)

        for i, track in enumerate(video_tracks):
            slot_id = track["slot_id"]
            layout  = track["layout"]
            start   = float(track["start"])
            end     = float(track["end"])
            dur     = end - start
            tw      = int(layout["w"])
            th      = int(layout["h"])
            tin     = track.get("transition_in", {})
            tin_type = tin.get("type", "cut")
            delay    = float(tin.get("delay", 0.0))
            appear   = start + delay

            ff_inputs += ["-i", normed[slot_id]]

            # Base chain: trim → reset pts → scale to cell → crop to cell
            # Shifting PTS by appear/TB aligns input frames with the timeline overlay window
            chain = (
                f"[{input_index}:v]"
                f"trim=duration={dur},"
                f"setpts=PTS-STARTPTS+{appear}/TB,"
                f"scale={tw}:{th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th}"
            )

            # Transition effects
            if tin_type == "slam":
                # Quick brightness flash on first 0.07s = slam feel, no zoompan
                chain += fr",eq=brightness='if(lt(t\,0.07)\,0.5\,0)'"

            elif tin_type == "fade":
                fade_dur = float(tin.get("duration", 0.3))
                # fade in from black over fade_dur seconds
                chain += f",fade=t=in:st=0:d={fade_dur}"

            # elif tin_type == "cut": nothing extra needed

            chain += f"[v{i}]"
            filter_parts.append(chain)
            input_index += 1

        # ── 3. Black canvas ───────────────────────────────────────────────
        filter_parts.append(
            f"color=black:size={W}x{H}:rate={FPS}:duration={total_dur}[bg]"
        )

        # ── 4. Overlay each video track onto the canvas ───────────────────
        #
        # Each track is enabled only between its [start+delay, end] window.
        # 'delay' lets you stagger slam cells: cell 0 at t=3.0, cell 1 at t=3.25 …

        current = "bg"
        for i, track in enumerate(video_tracks):
            layout  = track["layout"]
            start   = float(track["start"])
            end     = float(track["end"])
            px      = int(layout["x"])
            py      = int(layout["y"])
            tin     = track.get("transition_in", {})
            delay   = float(tin.get("delay", 0.0))
            appear  = start + delay
            next_l  = f"ov{i}"

            filter_parts.append(
                f"[{current}][v{i}]"
                f"overlay={px}:{py}:"
                f"enable='between(t,{appear},{end})'"
                f"[{next_l}]"
            )
            current = next_l

        # ── 5. Text overlays via drawtext ─────────────────────────────────
        #
        # Supports animations:
        #   slide_up  — text rises from y+60 to y over `duration` seconds
        #   fade      — opacity 0→1 (simulated via color, FFmpeg drawtext
        #               has no alpha; we skip true fade, just pop in)
        #   (default) — text appears instantly at start, disappears at end

        drawtext_chains = []
        if text_tracks and _drawtext_available():
            # Discover local font file to prevent missing font errors
            font_paths = [
                "/System/Library/Fonts/Supplemental/Arial.ttf",
                "/System/Library/Fonts/Helvetica.ttc",
                "/Library/Fonts/Arial.ttf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            ]
            font_file = next((p for p in font_paths if os.path.exists(p)), None)

            for t in text_tracks:
                content = t.get("content", {})
                # Use user-supplied value if present, else placeholder
                text = content.get("value") or content.get("placeholder", "")
                # Escape single quotes for FFmpeg using standard close-escape-reopen pattern
                text = text.replace("'", "'\\''").replace(":", "\\:")

                style  = t.get("style", {})
                anim   = t.get("animation", {})
                tstart = float(t["start"])
                tend   = float(t["end"])

                font_size  = int(style.get("size",  56))
                font_color = style.get("color", "#FFFFFF").lstrip("#")
                tx         = style.get("x", W // 2)
                ty         = int(style.get("y", H - 200))
                align      = style.get("align", "center")

                # x position: center-align by default
                if align == "center":
                    x_expr = f"{tx}-tw/2"
                elif align == "right":
                    x_expr = f"{tx}-tw"
                else:
                    x_expr = str(tx)

                # y animation
                anim_type = anim.get("type", "none")
                if anim_type == "slide_up":
                    adur   = float(anim.get("duration", 0.4))
                    offset = 60
                    y_expr = (
                        f"if(lt(t-{tstart}\\,{adur})\\,"
                        f"{ty}+{offset}*(1-(t-{tstart})/{adur})\\,"
                        f"{ty})"
                    )
                else:
                    y_expr = str(ty)

                use_box = style.get("box", False)
                drawtext_params = (
                    f"drawtext="
                    f"text='{text}'"
                )
                if font_file:
                    drawtext_params += f":fontfile='{font_file}'"
                drawtext_params += (
                    f":fontsize={font_size}"
                    f":fontcolor=0x{font_color}"
                    f":borderw=5"
                    f":bordercolor=black"
                    f":x={x_expr}"
                    f":y={y_expr}"
                    f":enable='between(t\\,{tstart}\\,{tend})'"
                )
                if use_box:
                    drawtext_params += (
                        f":box=1"
                        f":boxcolor=black@0.45"
                        f":boxborderw=12"
                    )
                drawtext_chains.append(drawtext_params)
        elif text_tracks:
            logger.warning("drawtext filter not available — skipping text overlays")

        if drawtext_chains:
            # Chain all drawtexts on the last video output
            combined = ",".join(drawtext_chains)
            filter_parts.append(f"[{current}]{combined}[final]")
            current = "final"

        # ── 6. Assemble and run FFmpeg ────────────────────────────────────
        filter_str = ";".join(filter_parts)

        cmd = (
            ["ffmpeg", "-y"]
            + ff_inputs
            + [
                "-filter_complex", filter_str,
                "-map", f"[{current}]",
                "-t", str(total_dur),
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-pix_fmt", "yuv420p", "-an",
                output_path,
            ]
        )
        _run(cmd, "universal render")

    logger.info(f"✅ [UniversalRenderer] Written to {output_path}")
    return output_path


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _normalize(src: str, dst: str, w: int, h: int, fps: int):
    """Scale+crop to canvas size, target fps, strip audio."""
    _run([
        "ffmpeg", "-y", "-i", src,
        "-vf", (
            f"scale={w}:{h}:force_original_aspect_ratio=increase,"
            f"crop={w}:{h},"
            f"fps={fps}"
        ),
        "-c:v", "libx264", "-preset", "fast", "-crf", "18",
        "-pix_fmt", "yuv420p", "-an",
        dst
    ], f"normalize {Path(src).name}")


def _run(cmd: list, label: str = "ffmpeg"):
    logger.info(f"🎬 [UniversalRenderer] {label}")
    logger.info(f"FFmpeg CMD: {' '.join(cmd)}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.stderr:
        logger.info(f"FFmpeg output ({label}):\n{result.stderr}")
    if result.returncode != 0:
        logger.error(f"FFmpeg error ({label}):\n{result.stderr[-3000:]}")
        raise RuntimeError(f"FFmpeg failed: {label}\n{result.stderr[-500:]}")