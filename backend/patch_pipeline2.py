import re

with open("app/services/pipeline_service.py", "r") as f:
    code = f.read()

# Replace the snapping logic with EDL logic
old_snap = """                if beat_map:
                    try:
                        from beat_sync.config import SNAP_TOLERANCE_SEC, MIN_CLIP_DURATION_SEC, VERBOSE_LOGGING
                        from beat_sync.segment_snapper import snap_segments_to_beats
                        
                        logging.info("  🎵 [BeatSync] Snapping final segments to beats...")
                        snapped_segs = snap_segments_to_beats(
                            segments=final_segs,
                            beat_map=beat_map,
                            snap_tolerance_sec=SNAP_TOLERANCE_SEC,
                            min_clip_duration_sec=MIN_CLIP_DURATION_SEC,
                            verbose=VERBOSE_LOGGING,
                            bgm_offset_sec=bgm_start_sec
                        )
                        final_segs = snapped_segs
                        beat_sync_applied = True"""

new_edl = """                if beat_map:
                    try:
                        from app.services.edl_service import build_edl
                        logging.info("  🎵 [BeatSync] Building Edit Decision List (EDL)...")
                        
                        edl_result = build_edl(final_segs, beat_map)
                        edl = edl_result["edl"]
                        accent_times = edl_result["accent_times"]
                        
                        # Convert EDL format back to final_segs format for DB storage
                        new_final_segs = []
                        for idx, slot in enumerate(edl):
                            new_final_segs.append({
                                "video_path": slot["source_file"],
                                "start_sec": slot["clip_in"],
                                "end_sec": slot["clip_out"],
                                "cut_time": slot["cut_time"],
                                "transition": slot["transition"]
                            })
                        final_segs = new_final_segs
                        beat_sync_applied = True
                        
                        # Make edl globally available for stitcher
                        global_edl_result = edl_result"""

code = code.replace(old_snap, new_edl)

# Replace the stitcher call
old_stitch = """                from app.services.stitch_service import build_reel_from_segments
                
                # Stitch the (possibly beat-snapped) final_segs
                build_reel_from_segments(
                    best_segments=final_segs, 
                    clips_dir=clips_dir, 
                    reel_path=reel_path,
                    bgm_path=bgm_path_str,
                    bgm_start_sec=bgm_start_sec
                )"""

new_stitch = """                from app.services.stitch_service import build_reel_from_edl
                
                if 'global_edl_result' in locals():
                    build_reel_from_edl(
                        edl=global_edl_result["edl"],
                        accent_times=global_edl_result["accent_times"],
                        beat_map=beat_map,
                        reel_path=reel_path
                    )
                else:
                    logging.error("No EDL generated!")
                    raise RuntimeError("No EDL generated")"""

code = code.replace(old_stitch, new_stitch)

with open("app/services/pipeline_service.py", "w") as f:
    f.write(code)

print("Patch applied.")
