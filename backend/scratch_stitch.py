import re

with open("app/services/stitch_service.py", "r") as f:
    code = f.read()

new_code = """
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

def build_reel_from_edl(edl: list, accent_times: list, beat_map, reel_path: Path):
    logger.info("  🎬 [Stitch] Starting Single-Graph FFmpeg render...")
    
    if not edl:
        raise ValueError("EDL is empty.")
        
    inputs = []
    filter_complex = ""
    
    # Pre-process EDL
    # Add handles for crossfades
    for i, slot in enumerate(edl):
        # Determine transition duration
        t_dur = 0.0
        t_type = slot["transition"]
        if t_type == "fade":
            t_dur = 0.1
        elif t_type == "whip_zoom":
            t_dur = 0.15
        elif t_type in ("wiperight", "fadeblack"):
            t_dur = 0.3
            
        slot["t_dur"] = t_dur
        
        # Adjust clip_out to provide handle for the next transition
        if i < len(edl) - 1:
            slot["clip_out"] += t_dur / 2.0
        # Adjust clip_in to provide handle for the previous transition
        if i > 0:
            slot["clip_in"] = max(0.0, slot["clip_in"] - (edl[i-1]["t_dur"] / 2.0))
            
    # Build Input list and Trim/Scale filters
    for i, slot in enumerate(edl):
        inputs.extend(["-i", slot["source_file"]])
        
        dur = slot["clip_out"] - slot["clip_in"]
        
        # Trim, reset PTS, scale to 1080x1920 (crop to fill)
        filter_complex += f"[{i}:v]trim=start={slot['clip_in']}:duration={dur},setpts=PTS-STARTPTS,"
        filter_complex += f"scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,"
        filter_complex += f"fps=30,format=yuv420p[v{i}];"
        
    # Build Accent Pulses
    # Apply pulses onto the trimmed segments before concatenating
    for t in accent_times:
        # Find which slot this accent falls into
        for i, slot in enumerate(edl):
            if slot["cut_time"] <= t < (slot["cut_time"] + slot["duration"]):
                # Calculate relative time inside the clip
                rel_t = t - slot["cut_time"]
                # Apply brightness pulse: eq=brightness
                filter_complex += f"[v{i}]eq=brightness='if(between(t,{rel_t},{rel_t+0.12}),0.08,0)'[v{i}_acc];"
                filter_complex = filter_complex.replace(f"[v{i}]", f"[v{i}_acc]", 1) # This is a bit hacky, but we just re-assign the label
                # To be safe, we just rename the label
                break
                
    # Fix the hack above properly:
    # Instead of replacing strings, we just append a new node
    # Actually, simpler: just apply all accents for a segment at once
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
            
    # Build Transitions
    last_out = f"[{edl[0]['out_label']}]"
    current_offset = edl[0]["duration"]
    
    for i in range(1, len(edl)):
        t_type = edl[i-1]["transition"]
        t_dur = edl[i-1]["t_dur"]
        next_label = f"[{edl[i]['out_label']}]"
        
        if t_type == "hard_cut" or t_dur == 0.0:
            # Concat
            filter_complex += f"{last_out}{next_label}concat=n=2:v=1:a=0[out{i}];"
            last_out = f"[out{i}]"
            current_offset += edl[i]["duration"]
        else:
            # Xfade
            if t_type == "whip_zoom":
                xfade_type = "distance" # 'whip_zoom' isn't standard, use distance or slideleft
            else:
                xfade_type = t_type
                
            filter_complex += f"{last_out}{next_label}xfade=transition={xfade_type}:duration={t_dur}:offset={current_offset}[out{i}];"
            last_out = f"[out{i}]"
            current_offset += edl[i]["duration"] - (t_dur / 2.0)
            
    filter_complex += f"{last_out}format=yuv420p[final_v]"
    
    # Build ffmpeg command
    cmd = ["ffmpeg", "-y"]
    cmd.extend(inputs)
    
    # Audio input
    cmd.extend(["-i", beat_map.bgm_path])
    
    # Trim audio to exact section
    filter_complex += f";[{len(edl)}:a]atrim=start={beat_map.best_section_start}:end={beat_map.best_section_end},asetpts=PTS-STARTPTS[final_a]"
    
    cmd.extend(["-filter_complex", filter_complex])
    cmd.extend(["-map", "[final_v]", "-map", "[final_a]"])
    cmd.extend(["-c:v", "libx264", "-c:a", "aac", "-b:a", "192k", "-shortest", str(reel_path)])
    
    logger.info(f"  🎬 [Stitch] Executing ffmpeg graph with {len(edl)} cuts...")
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        logger.info(f"  🎬 [Stitch] ✓ Render complete: {reel_path}")
    except subprocess.CalledProcessError as e:
        logger.error(f"  ⚠️ FFmpeg failed! Stderr:\\n{e.stderr}")
        raise RuntimeError(f"FFmpeg Single-Graph render failed: {e.stderr}")

"""

# Overwrite stitch_service.py entirely since the old one is no longer needed
with open("app/services/stitch_service.py", "w") as f:
    f.write(new_code)

print("Patch applied.")
