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
                try:
                    logger.info(f"Bucket {bucket} does not exist. Creating it.")
                    self.s3_client.create_bucket(Bucket=bucket)
                except Exception as e:
                    logger.warning(f"Failed to create bucket {bucket}: {e}")
            except Exception as e:
                logger.warning(f"Could not connect to Minio endpoint or check bucket {bucket}. Skipping. Error: {e}")

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
    def download_file(self, object_key: str, local_path: str):
        self.s3_client.download_file(self.bucket_name, object_key, local_path)
        
storage_service = StorageService()
