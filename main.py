#!/usr/bin/env python3
"""
main.py — Entry point for the Web-based Video Timeline Analyzer.
"""
import os
import sys
# Silence OpenCV internal FFmpeg/HEVC decoder warning spam
os.environ["OPENCV_FFMPEG_LOGLEVEL"] = "-8"

import logging
from pathlib import Path
from dotenv import load_dotenv
import webbrowser
from threading import Timer

from config import CONFIG

# Add editor_ui to path for Flask
sys.path.insert(0, str(Path(__file__).parent / "editor_ui"))
# pyrefly: ignore [missing-import]
from app import app

def main():
    load_dotenv()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("analyzer.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )
    logger = logging.getLogger(__name__)
    
    if not os.getenv("OPENROUTER_API_KEY") and not os.getenv("NVIDIA_API_KEY"):
        logger.warning("⚠️  Neither OPENROUTER_API_KEY nor NVIDIA_API_KEY was found in .env file.")
        logger.warning("   Make sure to set one of them before running the analysis in the UI.")
        
    # Ensure input_videos dir exists
    Path("input_videos").mkdir(exist_ok=True)
        
    host = CONFIG["editor_host"]
    port = CONFIG["editor_port"]
    
    url = f"http://{host}:{port}"
    logger.info(f"\n{'='*60}")
    logger.info(f"🎬 Video Analyzer Web UI started at {url} (Waitress Production Server)")
    logger.info(f"   Press Ctrl+C to stop.")
    logger.info(f"{'='*60}\n")
    
    # Auto-open browser
    Timer(1.0, lambda: webbrowser.open(url)).start()
    
    # Use Waitress for production-grade WSGI serving
    from waitress import serve
    serve(app, host=host, port=port)

if __name__ == "__main__":
    main()
