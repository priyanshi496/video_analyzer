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
        self._ensure_bucket()

    def _ensure_bucket(self):
        try:
            self.s3_client.head_bucket(Bucket=self.bucket_name)
        except ClientError:
            logger.info(f"Bucket {self.bucket_name} does not exist. Creating it.")
            self.s3_client.create_bucket(Bucket=self.bucket_name)

    def generate_presigned_url(self, object_key: str, expiration: int = 3600) -> str:
        try:
            response = self.s3_client.generate_presigned_url('get_object',
                                                            Params={'Bucket': self.bucket_name,
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
        
storage_service = StorageService()
