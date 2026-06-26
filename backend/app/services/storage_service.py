import boto3
from botocore.exceptions import ClientError
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

class StorageService:
    def __init__(self):
        self.s3_client = boto3.client(
            's3',
            endpoint_url=f"{'https' if settings.MINIO_SECURE else 'http'}://{settings.MINIO_ENDPOINT}",
            aws_access_key_id=settings.MINIO_ACCESS_KEY,
            aws_secret_access_key=settings.MINIO_SECRET_KEY,
            region_name="us-east-1"
        )
        self.bucket_name = settings.MINIO_BUCKET_NAME
        self.llm_logs_bucket = f"{settings.MINIO_BUCKET_NAME}-llm-logs"
        self._ensure_buckets()

    def _ensure_buckets(self):
        for bucket in [self.bucket_name, self.llm_logs_bucket]:
            try:
                self.s3_client.head_bucket(Bucket=bucket)
            except ClientError:
                logger.info(f"Bucket {bucket} does not exist. Creating it.")
                self.s3_client.create_bucket(Bucket=bucket)

    def generate_presigned_url(self, object_key: str, expiration: int = 3600, bucket: str = None) -> str:
        target_bucket = bucket or self.bucket_name
        try:
            response = self.s3_client.generate_presigned_url('get_object',
                                                            Params={'Bucket': target_bucket,
                                                                    'Key': object_key},
                                                            ExpiresIn=expiration)
        except ClientError as e:
            logger.error(e)
            return ""
        return response

    def upload_file_obj(self, file_obj, object_key: str, content_type: str = None):
        ExtraArgs = {'ContentType': content_type} if content_type else None
        self.s3_client.upload_fileobj(file_obj, self.bucket_name, object_key, ExtraArgs=ExtraArgs)
        return object_key

    def upload_log_text(self, text: str, object_key: str):
        import io
        file_obj = io.BytesIO(text.encode('utf-8'))
        self.s3_client.upload_fileobj(file_obj, self.llm_logs_bucket, object_key, ExtraArgs={'ContentType': 'text/markdown'})
    def object_exists(self, object_key: str, bucket: str = None) -> bool:
        target_bucket = bucket or self.bucket_name
        try:
            self.s3_client.head_object(Bucket=target_bucket, Key=object_key)
            return True
        except ClientError:
            return False

    def download_file(self, object_key: str, local_path: str, bucket: str = None):
        target_bucket = bucket or self.bucket_name
        self.s3_client.download_file(target_bucket, object_key, local_path)
        
    def upload_json(self, data: dict, object_key: str, bucket: str = None):
        import json, io
        target_bucket = bucket or self.bucket_name
        file_obj = io.BytesIO(json.dumps(data).encode('utf-8'))
        self.s3_client.upload_fileobj(file_obj, target_bucket, object_key, ExtraArgs={'ContentType': 'application/json'})

    def download_json(self, object_key: str, bucket: str = None) -> dict:
        import json, io
        target_bucket = bucket or self.bucket_name
        try:
            file_obj = io.BytesIO()
            self.s3_client.download_fileobj(target_bucket, object_key, file_obj)
            return json.loads(file_obj.getvalue().decode('utf-8'))
        except Exception as e:
            logger.warning(f"Failed to download or parse JSON from MinIO ({object_key}): {e}")
            return None

    def delete_object(self, object_key: str, bucket: str = None):
        target_bucket = bucket or self.bucket_name
        try:
            self.s3_client.delete_object(Bucket=target_bucket, Key=object_key)
        except ClientError as e:
            logger.error(f"Error deleting key {object_key} from bucket {target_bucket}: {e}")

    def delete_prefix(self, prefix: str, bucket: str = None):
        target_bucket = bucket or self.bucket_name
        try:
            paginator = self.s3_client.get_paginator('list_objects_v2')
            pages = paginator.paginate(Bucket=target_bucket, Prefix=prefix)
            delete_us = []
            for page in pages:
                if 'Contents' in page:
                    for obj in page['Contents']:
                        delete_us.append({'Key': obj['Key']})
            if delete_us:
                for i in range(0, len(delete_us), 1000):
                    self.s3_client.delete_objects(
                        Bucket=target_bucket,
                        Delete={'Objects': delete_us[i:i+1000]}
                    )
        except ClientError as e:
            logger.error(f"Error deleting prefix {prefix} from bucket {target_bucket}: {e}")


storage_service = StorageService()

