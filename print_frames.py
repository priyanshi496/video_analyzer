#!/usr/bin/env python3
import os
import sys
import argparse

try:
    import cv2
except ImportError:
    print("Error: OpenCV (opencv-python) is not installed in the current environment.")
    sys.exit(1)

def print_frames(video_path, start_frame=0, end_frame=180):
    if not os.path.exists(video_path):
        print(f"Error: File not found at '{video_path}'")
        return

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print(f"Error: Cannot open video '{video_path}'")
        return

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    
    print("=" * 60)
    print(f"Video: {os.path.basename(video_path)}")
    print(f"FPS: {fps:.2f} | Total Frames: {total_frames}")
    print(f"Printing frame range: {start_frame} to {min(end_frame, total_frames - 1)}")
    print("=" * 60)
    print(f"{'Frame #':<12}{'Seconds':<15}{'Milliseconds':<15}")
    print("-" * 60)

    for frame_idx in range(start_frame, min(end_frame + 1, total_frames)):
        time_sec = frame_idx / fps
        time_ms = int(time_sec * 1000)
        print(f"{frame_idx:<12}{time_sec:<15.3f}{time_ms:<15}")

    cap.release()
    print("=" * 60)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Print frame-accurate timestamps (seconds and milliseconds) for a video segment.")
    parser.add_argument("video_path", help="Path to the MP4/MOV video file")
    parser.add_argument("--start", type=int, default=0, help="Start frame index (default 0)")
    parser.add_argument("--end", type=int, default=180, help="End frame index (default 180)")

    args = parser.parse_args()
    print_frames(args.video_path, args.start, args.end)
