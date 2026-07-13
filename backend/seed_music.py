import os
import sys
import json
import logging
import tempfile

# Add the parent directory to python path so we can import app modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.services.storage_service import storage_service
from app.services.music_service import download_youtube_song

# Set up logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def seed_catalog():
    catalog_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app", "core", "music_catalog.json")
    if not os.path.exists(catalog_path):
        logger.error(f"Catalog file not found at {catalog_path}")
        return

    with open(catalog_path, "r") as f:
        catalog = json.load(f)

    logger.info(f"Loaded {len(catalog)} songs from catalog. Beginning seeding process...")

    with tempfile.TemporaryDirectory() as tmpdir:
        for idx, song in enumerate(catalog, 1):
            slug = song["slug"]
            minio_key = f"music/catalog/{slug}.mp3"
            query = song["query"]
            
            logger.info(f"[{idx}/{len(catalog)}] Checking {song['track']} by {song['artist']} ({slug})...")
            
            # Check if already exists in MinIO
            if storage_service.object_exists(minio_key):
                logger.info(f"  Already exists in MinIO. Skipping.")
                continue

            logger.info(f"  Not found in MinIO. Downloading: '{query}'...")
            local_path = os.path.join(tmpdir, f"{slug}.mp3")
            
            try:
                success = download_youtube_song(query, local_path)
                if success and os.path.exists(local_path):
                    logger.info(f"  Successfully downloaded. Uploading to MinIO key: {minio_key}...")
                    with open(local_path, "rb") as f_obj:
                        storage_service.upload_file_obj(f_obj, minio_key, content_type="audio/mpeg")
                    logger.info(f"  Successfully uploaded. Cleaning up local file.")
                    os.remove(local_path)
                else:
                    logger.error(f"  Failed to download song via yt-dlp.")
            except Exception as e:
                logger.error(f"  Error processing song {slug}: {e}")

    logger.info("Seeding process finished.")

if __name__ == "__main__":
    seed_catalog()
