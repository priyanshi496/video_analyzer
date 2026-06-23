import cv2
import numpy as np
import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)

def evaluate_frame(frame: np.ndarray) -> Tuple[float, float, float]:
    """
    Evaluates a single frame for sharpness and exposure.
    Returns: (sharpness, mean_brightness, contrast)
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
    mean_brightness = np.mean(gray)
    contrast = np.std(gray)
    return sharpness, mean_brightness, contrast

def extract_candidate_segments(
    video_path: str,
    window_sec: float = 2.0,
    stride_sec: float = 1.0,
    sample_fps: int = 5
) -> List[Dict]:
    """
    Extracts high-quality candidate segments from a video using OpenCV heuristics.
    Returns a list of dicts: { "start": float, "end": float, "quality_score": float, "motion_score": float }
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        logger.error(f"Failed to open {video_path} for CV analysis.")
        return []

    orig_fps = cap.get(cv2.CAP_PROP_FPS)
    if orig_fps <= 0: orig_fps = 30.0
    
    frame_skip = max(1, int(orig_fps / sample_fps))
    
    frames_data = [] # list of (time_sec, sharpness, brightness, contrast, flow_mag)
    
    prev_gray = None
    frame_idx = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        if frame_idx % frame_skip == 0:
            time_sec = frame_idx / orig_fps
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            
            # 1. Quality
            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
            brightness = np.mean(gray)
            contrast = np.std(gray)
            
            # 2. Motion (Optical Flow)
            flow_mag = 0.0
            if prev_gray is not None:
                # Resize for faster flow calculation
                curr_small = cv2.resize(gray, (0,0), fx=0.5, fy=0.5)
                prev_small = cv2.resize(prev_gray, (0,0), fx=0.5, fy=0.5)
                flow = cv2.calcOpticalFlowFarneback(prev_small, curr_small, None, 0.5, 3, 15, 3, 5, 1.2, 0)
                mag, _ = cv2.cartToPolar(flow[..., 0], flow[..., 1])
                flow_mag = np.mean(mag)
                
            prev_gray = gray
            frames_data.append({
                "time": time_sec,
                "sharpness": sharpness,
                "brightness": brightness,
                "contrast": contrast,
                "motion": flow_mag
            })
            
        frame_idx += 1
        
    cap.release()
    
    if not frames_data:
        return []
        
    # Analyze rolling windows
    candidates = []
    duration = frames_data[-1]["time"]
    
    start_t = 0.0
    while start_t + window_sec <= duration:
        end_t = start_t + window_sec
        # Get frames in this window
        window_frames = [f for f in frames_data if start_t <= f["time"] <= end_t]
        
        if window_frames:
            avg_sharpness = np.mean([f["sharpness"] for f in window_frames])
            avg_brightness = np.mean([f["brightness"] for f in window_frames])
            avg_contrast = np.mean([f["contrast"] for f in window_frames])
            avg_motion = np.mean([f["motion"] for f in window_frames])
            
            # Reject if too dark, too blown out, or too blurry
            # These thresholds should be relatively loose to just drop garbage
            is_valid = True
            if avg_brightness < 15 or avg_brightness > 240:
                is_valid = False
            if avg_sharpness < 10.0:  # extremely blurry
                is_valid = False
                
            if is_valid:
                # Normalize scores somewhat arbitrarily to 0-10 range for downstream
                # Sharpness usually 100-1000+
                q_score = min(10.0, (avg_sharpness / 500.0) * 5.0 + (avg_contrast / 50.0) * 5.0)
                m_score = min(10.0, avg_motion * 2.0)
                
                candidates.append({
                    "start_sec": round(start_t, 2),
                    "end_sec": round(end_t, 2),
                    "quality_score": round(q_score, 2),
                    "motion_score": round(m_score, 2)
                })
                
        start_t += stride_sec
        
    return candidates

def analyze_image(image_path: str) -> Dict:
    """
    Analyzes an image and returns a synthetic candidate dict.
    """
    img = cv2.imread(image_path)
    if img is None:
        return {"quality_score": 0.0, "motion_score": 0.0}
        
    sharpness, brightness, contrast = evaluate_frame(img)
    q_score = min(10.0, (sharpness / 500.0) * 5.0 + (contrast / 50.0) * 5.0)
    
    return {
        "start_sec": 0.0,
        "end_sec": 3.0,  # Synthetic duration for images
        "quality_score": round(q_score, 2),
        "motion_score": 0.0  # Images have zero motion
    }
