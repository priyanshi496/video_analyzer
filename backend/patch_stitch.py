import re

with open("app/services/stitch_service.py", "r") as f:
    code = f.read()

new_code = """import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

def build_reel_from_edl(edl: list, accent_times: list, beat_map, reel_path: Path):
    logger.info("  🎬 [Stitch] Starting Single-Graph FFmpeg render...")
    
    if not edl:
        raise ValueError("EDL is empty.")
        
    inputs = []
    filter_complex = ""
    
    for i, slot in enumerate(edl):
        t_dur = 0.0
        t_type = slot["transition"]
        if t_type == "fade":
            t_dur = 0.1
        elif t_type == "whip_zoom":
            t_dur = 0.15
        elif t_type in ("wiperight", "fadeblack"):
            t_dur = 0.3
            
        slot["t_dur"] = t_dur
        
        if i < len(edl) - 1:
            slot["clip_out"] += t_dur / 2.0
        if i > 0:
            slot["clip_in"] = max(0.0, slot["clip_in"] - (edl[i-1]["t_dur"] / 2.0))
            
    input_idx = 0
    for i, slot in enumerate(edl):
        layout = slot.get("layout", "crop")
        
        if layout == "grid_3":
            # 3 Inputs
            src_main = slot["source_file"]
            inputs.extend(["-i", src_main, "-i", src_main, "-i", src_main])
            
            c1_in = slot["clip_in"]
            c1_out = slot["clip_out"]
            dur = c1_out - c1_in
            
            # Additional sources might be identical files, but they have different start times
            adds = slot.get("additional_sources", [])
            c2_in = adds[0]["in"] if len(adds) > 0 else c1_in + 2.0
            c3_in = adds[1]["in"] if len(adds) > 1 else c1_in + 4.0
            
            idx1 = input_idx
            idx2 = input_idx + 1
            idx3 = input_idx + 2
            input_idx += 3
            
            # Trim all 3
            filter_complex += f"[{idx1}:v]trim=start={c1_in}:duration={dur},setpts=PTS-STARTPTS,scale=1080:607:force_original_aspect_ratio=increase,crop=1080:607,setsar=1[v{i}_1];"
            filter_complex += f"[{idx2}:v]trim=start={c2_in}:duration={dur},setpts=PTS-STARTPTS,scale=1080:607:force_original_aspect_ratio=increase,crop=1080:607,setsar=1[v{i}_2];"
            filter_complex += f"[{idx3}:v]trim=start={c3_in}:duration={dur},setpts=PTS-STARTPTS,scale=1080:607:force_original_aspect_ratio=increase,crop=1080:607,setsar=1[v{i}_3];"
            
            # Vstack them and pad
            filter_complex += f"[{v{i}_1}][{v{i}_2}][{v{i}_3}]vstack=inputs=3[v{i}_stack];"
            filter_complex += f"[v{i}_stack]pad=1080:1920:0:49:black[v{i}_base];"
            
        elif layout == "blur_bg":
            inputs.extend(["-i", slot["source_file"]])
            dur = slot["clip_out"] - slot["clip_in"]
            idx = input_idx
            input_idx += 1
            
            # Trim
            filter_complex += f"[{idx}:v]trim=start={slot['clip_in']}:duration={dur},setpts=PTS-STARTPTS[v{i}_raw];"
            # Split
            filter_complex += f"[v{i}_raw]split[v{i}_bg][v{i}_fg];"
            # Blur BG
            filter_complex += f"[v{i}_bg]scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,boxblur=20:20[v{i}_bg_b];"
            # Scale FG (fit into 1080x1920 without crop)
            filter_complex += f"[v{i}_fg]scale=1080:1920:force_original_aspect_ratio=decrease[v{i}_fg_s];"
            # Overlay
            filter_complex += f"[v{i}_bg_b][v{i}_fg_s]overlay=(W-w)/2:(H-h)/2:shortest=1[v{i}_base];"
            
        else:
            # Standard crop (for 9:16 vertical videos)
            inputs.extend(["-i", slot["source_file"]])
            dur = slot["clip_out"] - slot["clip_in"]
            idx = input_idx
            input_idx += 1
            
            filter_complex += f"[{idx}:v]trim=start={slot['clip_in']}:duration={dur},setpts=PTS-STARTPTS,"
            filter_complex += f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1[v{i}_base];"
            
        # Ensure correct fps and format before accent pulses
        filter_complex += f"[v{i}_base]fps=30,format=yuv420p[v{i}];"
        
    for i, slot in enumerate(edl):
        accents_in_slot = [t for t in accent_times if slot["cut_time"] <= t < (slot["cut_time"] + slot["duration"])]
        if accents_in_slot:
            eq_filters = []
            for t in accents_in_slot:
                rel_t = t - slot["cut_time"]
                eq_filters.append(f"if(between(t,{rel_t},{rel_t+0.12}),0.08,0)")
            eq_expr = "+".join(eq_filters)
            filter_complex += f"[v{i}]eq=brightness='{eq_expr}'[v{i}_acc];"
            slot["out_label"] = f"v{i}_acc"
        else:
            slot["out_label"] = f"v{i}"
            
    last_out = f"[{edl[0]['out_label']}]"
    current_offset = edl[0]["duration"]
    
    for i in range(1, len(edl)):
        t_type = edl[i-1]["transition"]
        t_dur = edl[i-1]["t_dur"]
        next_label = f"[{edl[i]['out_label']}]"
        
        if t_type == "hard_cut" or t_dur == 0.0:
            filter_complex += f"{last_out}{next_label}concat=n=2:v=1:a=0[out{i}];"
            last_out = f"[out{i}]"
            current_offset += edl[i]["duration"]
        else:
            xfade_type = "distance" if t_type == "whip_zoom" else t_type
            filter_complex += f"{last_out}{next_label}xfade=transition={xfade_type}:duration={t_dur}:offset={current_offset}[out{i}];"
            last_out = f"[out{i}]"
            current_offset += edl[i]["duration"] - (t_dur / 2.0)
            
    filter_complex += f"{last_out}format=yuv420p[final_v]"
    
    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    cmd.extend(["-i", beat_map.bgm_path])
    
    filter_complex += f";[{input_idx}:a]atrim=start={beat_map.best_section_start}:end={beat_map.best_section_end},asetpts=PTS-STARTPTS[final_a]"
    
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "[final_v]", "-map", "[final_a]"])
    cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest", str(reel_path)])
    
    logger.info(f"  🎬 [Stitch] Executing ffmpeg graph with {len(edl)} cuts...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        logger.info(f"  🎬 [Stitch] ✓ Render complete: {reel_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"  ⚠️ FFmpeg failed! Stderr:\n{e.stderr}")
        raise RuntimeError(f"FFmpeg Single-Graph render failed: {e.stderr}")
"""

# There is a small typo in the f-string for vstack: `f"[{v{i}_1}]"` should be `f"[v{i}_1]"`
new_code = new_code.replace('f"[{v{i}_1}][{v{i}_2}][{v{i}_3}]vstack', 'f"[v{i}_1][v{i}_2][v{i}_3]vstack')

with open("app/services/stitch_service.py", "w") as f:
    f.write(new_code)

print("stitch_service patched.")
