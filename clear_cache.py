#!/usr/bin/env python3
"""
clear_cache.py — Production-ready workspace reset utility.
Run this script to cleanly reset your workspace before starting a new analysis project.

Usage:
  .venv/bin/python clear_cache.py         -> Resets cache, timeline frames, temp clips, and output files. (Asks to clear raw inputs)
  .venv/bin/python clear_cache.py --all   -> Wipes everything, including raw input videos, immediately.
"""
import sys
import shutil
from pathlib import Path

def clear_directory(path: Path, label: str):
    if path.exists():
        try:
            shutil.rmtree(path)
            path.mkdir(exist_ok=True)
            print(f"  ✓ Emptied: {label}/")
        except Exception as e:
            print(f"  ✗ Failed to clear {label}: {e}")
    else:
        try:
            path.mkdir(exist_ok=True)
            print(f"  ✓ Created missing directory: {label}/")
        except Exception as e:
            print(f"  ✗ Failed to create directory {label}: {e}")

def delete_file(path: Path, label: str):
    if path.exists():
        try:
            path.unlink()
            print(f"  ✓ Removed: {label}")
        except Exception as e:
            print(f"  ✗ Failed to delete {label}: {e}")

def main():
    # Check for non-interactive override argument
    wipe_inputs = "--all" in sys.argv or "-a" in sys.argv

    print("\n============================================================")
    print("🧹 VIDEO ANALYZER WORKSPACE RESET UTILITY")
    print("============================================================\n")

    # 1. Clear LLM Analysis Cache
    delete_file(Path("logs/analysis_cache.json"), "logs/analysis_cache.json")

    # 2. Clear Selected Segments Metadata
    delete_file(Path("best_segments.json"), "best_segments.json")

    # 3. Clear Output Reel
    delete_file(Path("final_highlight_reel.mp4"), "final_highlight_reel.mp4")

    # 4. Clear Timeline Frame Images
    clear_directory(Path("timeline_frames"), "timeline_frames")

    # 5. Clear Trimmed Clip Highlights
    clear_directory(Path("clips"), "clips")

    # 6. Optional: Clear Raw Input Videos
    input_dir = Path("input_videos")
    if input_dir.exists():
        extensions = ("*.mp4", "*.mov", "*.MOV", "*.mkv", "*.avi", "*.webm", "*.jpg", "*.jpeg", "*.png", "*.heic")
        raw_videos = []
        for ext in extensions:
            raw_videos.extend(input_dir.glob(ext))
        if raw_videos:
            if not wipe_inputs:
                print(f"\n📂 Found {len(raw_videos)} raw video file(s) in input_videos/.")
                user_choice = input("   Do you want to delete these input videos to start fresh? [y/N]: ").strip().lower()
                wipe_inputs = user_choice in ("y", "yes")

            if wipe_inputs:
                print()
                for vid in raw_videos:
                    delete_file(vid, f"input_videos/{vid.name}")
            else:
                print("\n  - Kept raw input videos in input_videos/.")
        else:
            print("\n  - No raw input videos found in input_videos/.")
    else:
        input_dir.mkdir(exist_ok=True)
        print("\n  ✓ Created missing input_videos/ directory.")

    print("\n✨ Done! Your workspace is completely clean and production-ready.")
    print("   Upload your new videos and start main.py fresh!\n")

if __name__ == "__main__":
    main()
