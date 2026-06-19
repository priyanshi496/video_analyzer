import os
import sys
import shutil
import tempfile
import logging

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.storage_service import storage_service
from app.services.music_service import (
    resolve_custom_music,
    pick_ai_music,
    mix_music_into_video,
    get_video_duration
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def run_tests():
    logger.info("Starting music feature tests...")
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # Test Case 1: Custom music resolution and cache
        logger.info("\n--- TEST 1: Custom Music Resolution ---")
        
        # Test 1A: Check that a short-form catalog name (e.g., "sahiba") resolves to catalog path
        logger.info("Resolving short-form catalog name 'sahiba'...")
        path_cat = resolve_custom_music("sahiba", tmpdir)
        logger.info(f"Resolution path for sahiba: {path_cat}")
        assert "sahiba-aditya-rikhari.mp3" in path_cat, f"Should resolve to sahiba catalog mp3, got {path_cat}"
        
        # Test 1B: Check that a non-catalog short-form query (e.g. "yarana") gets expanded and resolved
        custom_query = "yarana"
        logger.info(f"Resolving non-catalog short-form: '{custom_query}'")
        path1 = resolve_custom_music(custom_query, tmpdir)
        logger.info(f"Resolution path for yarana: {path1}")
        assert os.path.exists(path1), "Custom music file does not exist!"
        assert path1.endswith(".mp3"), "Should be an mp3 file!"
        
        # Test 1C: Caching verification (resolving again should hit MinIO cache)
        logger.info("Resolving 'yarana' again to verify cache hit...")
        path2 = resolve_custom_music(custom_query, tmpdir)
        logger.info(f"Second resolution path: {path2}")
        assert os.path.exists(path2), "Cached custom music file does not exist!"
        
        # Test Case 2: AI music selection scoring
        logger.info("\n--- TEST 2: AI Music Picker Scorer ---")
        # Dummy segments resembling active sports / energetic scene
        energetic_segs = [
            {"mood": "energetic", "overall_mood": "very high energy", "overall_vibe": "active", "video_summary": "a man running and jumping in a gym", "what_happens": "workout"},
            {"mood": "excited", "overall_mood": "fast paced action", "overall_vibe": "energetic", "video_summary": "a close up of weightlifting", "what_happens": "intense workout"}
        ]
        logger.info("Testing energetic vibe scoring...")
        ai_path_energetic = pick_ai_music("energetic", energetic_segs, tmpdir)
        logger.info(f"AI energetic path: {ai_path_energetic}")
        
        # Dummy segments resembling a calm / emotional scene
        romantic_segs = [
            {"mood": "romantic", "overall_mood": "peaceful couples dinner", "overall_vibe": "chill", "video_summary": "a couple sitting by the fireplace, talking gently", "what_happens": "love scene"},
            {"mood": "soft", "overall_mood": "calm warm atmosphere", "overall_vibe": "dreamy and slow", "video_summary": "golden hour shot of the sunset", "what_happens": "scenic landscape"}
        ]
        logger.info("Testing romantic vibe scoring...")
        ai_path_romantic = pick_ai_music("romantic", romantic_segs, tmpdir)
        logger.info(f"AI romantic path: {ai_path_romantic}")
        
        # Test Case 3: Music-Video mixing and 1s fade-out
        logger.info("\n--- TEST 3: Music-Video Mixing ---")
        # Download a test video from MinIO
        test_video_key = "projects/205159d3-1e80-41c7-9965-2e7027ef3578/jobs/2478734a-ba6f-426e-ad5b-e4da4a181fc0/final_video.mp4"
        local_video = os.path.join(tmpdir, "test_video.mp4")
        logger.info(f"Downloading test video from MinIO key '{test_video_key}' to '{local_video}'...")
        try:
            storage_service.download_file(test_video_key, local_video)
        except Exception as e:
            logger.error(f"Could not download test video: {e}")
            logger.info("Skipping mixing test (requires existing MinIO video).")
            return
            
        video_dur = get_video_duration(local_video)
        logger.info(f"Test video duration: {video_dur:.2f} seconds")
        
        mixed_video = os.path.join(tmpdir, "mixed_video.mp4")
        # Mix the custom music (which we downloaded in Test 1) into this video
        logger.info("Mixing background music and applying 1s fade-out...")
        mix_music_into_video(local_video, path1, mixed_video)
        
        assert os.path.exists(mixed_video), "Mixed video was not created!"
        mixed_dur = get_video_duration(mixed_video)
        logger.info(f"Mixed video duration: {mixed_dur:.2f} seconds")
        
        # Duration should be identical (within tolerance)
        assert abs(mixed_dur - video_dur) < 0.1, f"Video durations do not match! Original: {video_dur}, Mixed: {mixed_dur}"
        
        # Save a copy to the workspace directory to manually verify audio if desired
        out_copy = "test_mixed_output.mp4"
        shutil.copy(mixed_video, out_copy)
        logger.info(f"Saved copy of mixed video to '{out_copy}' for verification.")

    logger.info("\nAll tests completed successfully!")

if __name__ == "__main__":
    run_tests()
