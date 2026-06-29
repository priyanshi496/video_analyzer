#!/usr/bin/env python3
import os
import sys
import argparse

try:
    import cv2
    import numpy as np
except ImportError:
    print("Error: OpenCV (opencv-python) or numpy is not installed in the current environment.")
    print("Please install them using: pip install opencv-python numpy")
    sys.exit(1)

def detect_cuts(video_path, threshold=0.6, min_scene_len_frames=5):
    """
    Detects scene cuts/transitions using pixel-wise HSV histogram difference
    and frame-to-frame average intensity differences.
    """
    if not os.path.exists(video_path):
        print(f"Error: File not found at '{video_path}'")
        return

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video '{video_path}'")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    if fps <= 0:
        fps = 30.0

    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    print("=" * 60)
    print(f"Analyzing: {os.path.basename(video_path)}")
    print(f"Resolution: {width}x{height} | FPS: {fps:.2f} | Total Frames: {total_frames}")
    print(f"Threshold: {threshold} (lower = more sensitive to cuts)")
    print("=" * 60)

    thumb_dir = "detected_cuts_thumbnails"
    os.makedirs(thumb_dir, exist_ok=True)

    prev_hsv = None
    cuts = []
    last_cut_frame = -min_scene_len_frames

    # Start loop
    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # Downscale to speed up processing
        small_frame = cv2.resize(frame, (180, 320))
        hsv = cv2.cvtColor(small_frame, cv2.COLOR_BGR2HSV)

        if prev_hsv is not None:
            # 1. Compare Hue and Saturation Histograms
            hist_curr = cv2.calcHist([hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
            hist_prev = cv2.calcHist([prev_hsv], [0, 1], None, [30, 32], [0, 180, 0, 256])
            
            cv2.normalize(hist_curr, hist_curr, 0, 1, cv2.NORM_MINMAX)
            cv2.normalize(hist_prev, hist_prev, 0, 1, cv2.NORM_MINMAX)

            hist_score = cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)

            # 2. Compare absolute frame differences
            abs_diff = cv2.absdiff(hsv[:, :, 2], prev_hsv[:, :, 2])
            mean_diff = np.mean(abs_diff) / 255.0

            # Combine scores: low histogram correlation OR high average pixel changes indicates a cut
            is_cut = (hist_score < threshold) or (mean_diff > 0.35)

            if is_cut and (frame_idx - last_cut_frame >= min_scene_len_frames):
                timestamp_sec = frame_idx / fps
                timestamp_ms = int(timestamp_sec * 1000)
                
                cuts.append({
                    "frame": frame_idx,
                    "sec": timestamp_sec,
                    "ms": timestamp_ms,
                    "hist_score": hist_score,
                    "pixel_diff": mean_diff
                })

                # Save thumbnails
                # Frame right before the cut
                cv2.imwrite(os.path.join(thumb_dir, f"cut_{len(cuts):02d}_A_before_{timestamp_sec:.2f}s.jpg"), prev_frame)
                # Frame at the cut
                cv2.imwrite(os.path.join(thumb_dir, f"cut_{len(cuts):02d}_B_after_{timestamp_sec:.2f}s.jpg"), frame)

                last_cut_frame = frame_idx

        prev_hsv = hsv
        prev_frame = frame.copy()
        frame_idx += 1

    cap.release()

    print("\n" + "#" * 70)
    print("                DETECTED VIDEO CUT TIMESTAMPS")
    print("#" * 70)
    print(f"{'Cut #':<8}{'Frame':<10}{'Seconds':<12}{'Milliseconds':<15}{'Confidence':<12}")
    print("-" * 70)
    
    # Always include 0.00s as the first scene start
    print(f"{'Start':<8}{'0':<10}{'0.000':<12}{'0':<15}{'1.000':<12}")

    for idx, cut in enumerate(cuts):
        # Confidence score based on histogram correlation (lower correlation = higher confidence)
        confidence = max(0.0, 1.0 - cut["hist_score"])
        print(f"{idx + 1:<8}{cut['frame']:<10}{cut['sec']:<12.3f}{cut['ms']:<15}{confidence:<12.3f}")

    print(f"{'End':<8}{total_frames:<10}{total_frames/fps:<12.3f}{int(total_frames/fps*1000):<15}{'1.000':<12}")
    print("-" * 70)
    print(f"Total Detected Cuts: {len(cuts)}")
    print(f"Thumbnails saved in folder: './{thumb_dir}/'")
    print("=" * 70)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Analyze a video file and detect exact cuts/scene transition timestamps.")
    parser.add_argument("video_path", help="Path to the MP4/MOV video file")
    parser.add_argument("--threshold", type=float, default=0.55, help="Cut sensitivity threshold (default 0.55, range 0.1 to 0.9)")
    parser.add_argument("--min-len", type=int, default=5, help="Minimum frame duration of a scene to avoid double-detection (default 5)")

    args = parser.parse_args()
    detect_cuts(args.video_path, args.threshold, args.min_len)
