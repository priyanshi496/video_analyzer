import logging
import math
from typing import List, Dict

logger = logging.getLogger(__name__)

def build_edl(clip_pool: List[Dict], beat_map) -> List[Dict]:
    logger.info("  [EDL] Starting Stage 3: Sequential Assignment (Every Beat)")
    
    cut_times = []
    accent_times = []
    
    for beat in beat_map.beat_grid:
        cut_times.append(beat)
            
    if not cut_times or cut_times[0]["time"] > 0.1:
        cut_times.insert(0, {"time": 0.0, "is_downbeat": True, "strength": 0.5})
        
    slots = []
    for i in range(len(cut_times) - 1):
        dur = cut_times[i+1]["time"] - cut_times[i]["time"]
        if dur < 0.2:
            continue
        slots.append({
            "start_time": cut_times[i]["time"],
            "duration": dur,
            "energy": cut_times[i]["strength"],
            "is_downbeat": cut_times[i]["is_downbeat"]
        })
        
    last_dur = (beat_map.best_section_end - beat_map.best_section_start) - cut_times[-1]["time"]
    if last_dur > 0.2:
        slots.append({
            "start_time": cut_times[-1]["time"],
            "duration": last_dur,
            "energy": cut_times[-1]["strength"],
            "is_downbeat": cut_times[-1]["is_downbeat"]
        })
        
    logger.info(f"  [EDL] Generated {len(slots)} cut slots.")
    
    available_clips = []
    for i, c in enumerate(clip_pool):
        c["story_idx"] = i
        c["use_count"] = 0
        available_clips.append(c)
        
    assigned_slots = [None] * len(slots)
    prev_story_idx = -1
    
    for i, slot in enumerate(slots):
        best_clip = None
        best_score = -float('inf')
        
        prev_source = assigned_slots[i - 1]["source_file"] if i > 0 and assigned_slots[i - 1] else None
        if isinstance(prev_source, list):
            prev_source = prev_source[0]
        
        for clip in available_clips:
            if clip["use_count"] >= 4: # Allow more reuse but heavily penalize it
                continue
                
            prog_score = 0.0
            if clip["story_idx"] == prev_story_idx + 1:
                prog_score = 15.0
            elif clip["story_idx"] > prev_story_idx:
                prog_score = 5.0
            elif clip["story_idx"] == 0 and prev_story_idx >= len(available_clips) - 1:
                prog_score = 10.0
            else:
                prog_score = -5.0
                
            energy_match = 1.0 - abs(clip.get("motion_score", 0)/10.0 - slot["energy"])
            quality = clip.get("final_score", 5.0) / 10.0
            
            duration_available = clip.get("end_sec", 0.0) - clip.get("start_sec", 0.0)
            
            # If a clip is reused, we will shift its start point
            proposed_in = clip.get("start_sec", 0.0) + (clip["use_count"] * slot["duration"])
            
            if clip.get("is_image", False):
                duration_available = 999.0  # Images can be shown forever
                proposed_in = 0.0
            elif proposed_in + slot["duration"] <= clip.get("end_sec", 0.0):
                duration_available = clip.get("end_sec", 0.0) - proposed_in
            else:
                duration_available = 0.0  # Shifted too far, no duration left!
                
            if duration_available < slot["duration"]:
                dur_penalty = -1000.0
            else:
                dur_penalty = 0.0
                
            div_penalty = 0.0
            if clip.get("video_path", clip.get("source_file")) == prev_source:
                div_penalty = -5000.0
                
            source_file = clip.get("video_path", clip.get("source_file"))
            source_use_count = sum(1 for s in assigned_slots if s and s["source_file"] == source_file)
            source_bonus = 50.0 if source_use_count == 0 else 0.0
                
            use_penalty = -100.0 * clip["use_count"]
            use_penalty = -500.0 * clip["use_count"]
            
            fit_score = prog_score + (energy_match * 3.0) + (quality * 4.0) + dur_penalty + div_penalty + use_penalty + source_bonus
            
            if fit_score > best_score:
                best_score = fit_score
                best_clip = clip
                
        if best_clip:
            best_clip["use_count"] += 1
            prev_story_idx = best_clip["story_idx"]
            
            layout = "crop" # default for 9:16 or unknown
            source_file = best_clip.get("video_path", best_clip.get("source_file"))
            
            # Shift clip_in if reused so we don't show the same frames
            clip_in = best_clip.get("start_sec", 0.0) + ((best_clip["use_count"] - 1) * slot["duration"])
            if not best_clip.get("is_image", False):
                # Ensure we never go past the video bounds, but do NOT reset to 0 to avoid duplicates
                max_in = max(best_clip.get("start_sec", 0.0), best_clip.get("end_sec", 0.0) - slot["duration"])
                clip_in = min(clip_in, max_in)
                
            clip_out = clip_in + slot["duration"]
            
            additional_sources = []
            
            if best_clip.get("is_landscape", False) and not best_clip.get("is_image", False) and slot["duration"] >= 1.2:
                layout = "grid_3"
                # Look for 2 more clips from DIFFERENT landscape videos
                other_landscape_clips = [c for c in available_clips if c.get("is_landscape", False) and not c.get("is_image", False) and c.get("video_path", c.get("source_file")) != source_file and c["use_count"] == 0]
                # Filter for duration
                other_landscape_clips = [c for c in other_landscape_clips if (c.get("end_sec",0) - c.get("start_sec",0)) >= slot["duration"]]
                
                if len(other_landscape_clips) >= 2:
                    c2 = other_landscape_clips[0]
                    c3 = other_landscape_clips[1]
                    c2["use_count"] += 1
                    c3["use_count"] += 1
                    
                    additional_sources = [
                        {"source": c2.get("video_path", c2.get("source_file")), "in": c2.get("start_sec", 0.0), "out": c2.get("start_sec", 0.0) + slot["duration"]},
                        {"source": c3.get("video_path", c3.get("source_file")), "in": c3.get("start_sec", 0.0), "out": c3.get("start_sec", 0.0) + slot["duration"]}
                    ]
                else:
                    layout = "blur_bg"
            
            if slot["is_downbeat"] and slot["energy"] > 0.8:
                transition = "fade"
            elif slot["is_downbeat"]:
                transition = "hard_cut"
            else:
                transition = "hard_cut"
                
            assigned_slots[i] = {
                "cut_time": slot["start_time"],
                "duration": slot["duration"],
                "source_file": source_file,
                "clip_in": clip_in,
                "clip_out": clip_out,
                "transition": transition,
                "layout": layout,
                "additional_sources": additional_sources
            }
        else:
            # Fallback
            c0 = clip_pool[0]
            layout = "blur_bg" if c0.get("is_landscape") else "crop"
            assigned_slots[i] = {
                "cut_time": slot["start_time"],
                "duration": slot["duration"],
                "source_file": c0.get("video_path", c0.get("source_file")),
                "clip_in": 0.0,
                "clip_out": slot["duration"],
                "transition": "hard_cut",
                "layout": layout,
                "additional_sources": []
            }
            
    logger.info(f"  [EDL] Assigned {len(assigned_slots)} clips.")
    
    return {
        "edl": assigned_slots,
        "accent_times": accent_times
    }
