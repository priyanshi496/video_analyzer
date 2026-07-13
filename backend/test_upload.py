import asyncio
import os
import sys
sys.path.append('.')
from app.services.storage_service import storage_service
from io import BytesIO

async def main():
    test_data = b"Hello, MinIO!"
    file_obj = BytesIO(test_data)
    object_key = "test_upload.txt"
    await asyncio.to_thread(storage_service.upload_file_obj, file_obj, object_key, "text/plain")
    
    # Verify
    objs = storage_service.s3_client.list_objects_v2(Bucket=storage_service.bucket_name)
    keys = [o['Key'] for o in objs.get('Contents', [])]
    print("Keys after upload:", keys)

asyncio.run(main())
