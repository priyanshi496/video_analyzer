import re
import sys

with open("app/services/pipeline_service.py", "r") as f:
    code = f.read()

# Replace process_single_video
new_process = """
def process_single_video(
    info: dict,
    api_key: str,
    video_quality_map: dict,
    reference_paths: list,
    directives: str = "",
    audio_analysis: dict = None,
    total_footage_sec: float = 0.0,
) -> dict:
    import uuid
    import logging
    from app.services.cv_service import extract_candidate_segments, analyze_image
    from app.services.frames_service import extract_frame_at_time
    from app.services.prompts_service import build_candidate_scoring_prompt, parse_json_response
    from app.services.llm_service import call_openrouter_multiimage

    path = info["path"]
    dur = info.get("duration_sec", 0.0)
    is_image = info.get("is_image", False)
    
    logging.info(f"\\n▶ [Stage 1] Pre-filtering {path} ({dur:.1f}s)")

    # 1. OpenCV Pre-Filter
    if is_image:
        candidates = [analyze_image(path)]
    else:
        candidates = extract_candidate_segments(path, window_sec=2.0, stride_sec=1.0)
        
    if not candidates:
        logging.warning(f"  ⚠️ No valid candidates found in {path}")
        return {"video_path": path, "duration_sec": dur, "analysis": {"best_segments": []}}

    # 2. Dynamic Thresholding based on total_footage_sec
    if total_footage_sec > 60:
        top_pct = 0.3
    elif total_footage_sec > 30:
        top_pct = 0.5
    else:
        top_pct = 0.8
        
    candidates.sort(key=lambda c: c.get("quality_score", 0) + c.get("motion_score", 0), reverse=True)
    num_keep = max(1, int(len(candidates) * top_pct))
    surviving_candidates = candidates[:num_keep]
    logging.info(f"  ✓ CV Filter: Kept {num_keep}/{len(candidates)} candidates.")

    # 3. Extract thumbnails for LLM
    for i, c in enumerate(surviving_candidates):
        c["segment_id"] = f"seg_{i}_{uuid.uuid4().hex[:4]}"
        mid_time = c["start_sec"] + (c["end_sec"] - c["start_sec"]) / 2
        c["thumbnail"] = extract_frame_at_time(path, mid_time)
        
    # 4. Batch to LLM
    batch_size = 10
    final_segments = []
    
    for i in range(0, len(surviving_candidates), batch_size):
        batch = surviving_candidates[i:i+batch_size]
        prompt = build_candidate_scoring_prompt(batch, directives)
        image_paths = [c["thumbnail"] for c in batch if c.get("thumbnail")]
        
        try:
            raw, parsed = call_openrouter_multiimage(prompt, image_paths, api_key=api_key)
            parsed_list = parse_json_response(parsed)
            if isinstance(parsed_list, list):
                for p in parsed_list:
                    seg_id = p.get("segment_id")
                    match = next((c for c in batch if c.get("segment_id") == seg_id), None)
                    if match:
                        match["aesthetic_score"] = p.get("aesthetic_score", 5)
                        match["emotion_tag"] = p.get("emotion_tag", "neutral")
                        match["scene_type"] = p.get("scene_type", "action")
                        match["caption"] = p.get("caption", "")
                        
                        match["final_score"] = match["quality_score"]*0.3 + match["motion_score"]*0.2 + match.get("aesthetic_score", 5)*0.5
                        match["priority"] = 100 - match["final_score"] # lower is better for old logic compatibility
                        match["reason"] = match["caption"]
                        match["narrative_role"] = match["scene_type"]
                        final_segments.append(match)
        except Exception as e:
            logging.error(f"  ⚠️ LLM scoring failed for batch: {e}")
            # fallback: add batch with average scores
            for c in batch:
                c["final_score"] = c["quality_score"]*0.3 + c["motion_score"]*0.2 + 5*0.5
                c["priority"] = 100 - c["final_score"]
                final_segments.append(c)
                
    logging.info(f"  ✓ Scored {len(final_segments)} segments via Nemotron.")

    return {
        "video_path": path,
        "duration_sec": dur,
        "analysis": {
            "best_segments": final_segments
        }
    }
"""

code = re.sub(r'def process_single_video\(.*?return res', new_process, code, flags=re.DOTALL)

# Modify run_full_analysis to calculate total_footage_sec
new_run_full = """def run_full_analysis(
    video_infos: list,
    api_key: str,
    video_quality_map: dict,
    reference_paths: list,
    directives: str = "",
    use_uploaded_order: bool = False,
    progress_callback = None,
    audio_analysis: dict = None,
    beat_windows: list = None,
) -> list:
    import time
    import logging
    from concurrent.futures import ThreadPoolExecutor
    import concurrent.futures

    pipeline_start_time = time.time()
    
    total_footage_sec = sum(info.get("duration_sec", 0.0) for info in video_infos)

    logging.info(f"\\n{'='*60}")
    logging.info(f"Analyzing {len(video_infos)} video(s) (Total {total_footage_sec:.1f}s) in parallel...")
    logging.info(f"{'='*60}")

    max_workers = min(len(video_infos) or 1, 3)
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [
            ex.submit(process_single_video, info, api_key, video_quality_map, reference_paths, directives, audio_analysis, total_footage_sec)
            for info in video_infos
        ]
        
        all_results = []
        for future in concurrent.futures.as_completed(futures):
            all_results.append(future.result())
            if progress_callback:
                progress_callback()

    best_segments = []
    for result in all_results:
        segs = sorted(result["analysis"].get("best_segments", []), key=lambda s: float(s.get("start_sec", 0)))
        for seg in segs:
            seg["source_file"] = result["video_path"]
            seg["duration_available"] = seg["end_sec"] - seg["start_sec"]
            best_segments.append(seg)
            
    # Return both the flat best_segments pool and all_results
    return best_segments, all_results
"""

code = re.sub(r'def run_full_analysis\(.*?return best_segments, all_results', new_run_full, code, flags=re.DOTALL)

with open("app/services/pipeline_service.py", "w") as f:
    f.write(code)

print("Patch applied.")
