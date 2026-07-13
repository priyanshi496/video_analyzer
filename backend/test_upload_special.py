import asyncio
import os
import sys
import requests
sys.path.append('.')
from app.services.storage_service import storage_service
from io import BytesIO

async def main():
    test_data = b"Hello, MinIO!"
    file_obj = BytesIO(test_data)
    object_key = "test folder/download (1).jpeg"
    
    # 1. Upload
    await asyncio.to_thread(storage_service.upload_file_obj, file_obj, object_key, "image/jpeg")
    
    # 2. List
    objs = storage_service.s3_client.list_objects_v2(Bucket=storage_service.bucket_name, Prefix="test folder/")
    keys = [o['Key'] for o in objs.get('Contents', [])]
    print("Keys after upload:", keys)
    
    # 3. Generate presigned URL
    url = storage_service.generate_presigned_url(object_key)
    print("Presigned URL:", url)
    
    # 4. Try to download it with requests
    r = requests.get(url)
    print(f"Download status: {r.status_code}")
    if r.status_code != 200:
        print("Response:", r.content)

asyncio.run(main())
