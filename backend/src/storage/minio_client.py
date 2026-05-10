import os
import logging
from typing import Optional, Dict, Any, BinaryIO
from pathlib import Path
import minio
from minio.error import S3Error

logger = logging.getLogger("storage")

MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "deepseek-projects")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"


class MinioStorage:
    def __init__(
        self,
        endpoint: str = MINIO_ENDPOINT,
        access_key: str = MINIO_ACCESS_KEY,
        secret_key: str = MINIO_SECRET_KEY,
        bucket: str = MINIO_BUCKET,
        secure: bool = MINIO_SECURE,
    ):
        self.endpoint = endpoint
        self.access_key = access_key
        self.secret_key = secret_key
        self.bucket = bucket
        self.secure = secure
        self._client: Optional[minio.Minio] = None

    @property
    def client(self) -> minio.Minio:
        if self._client is None:
            self._client = minio.Minio(
                self.endpoint,
                access_key=self.access_key,
                secret_key=self.secret_key,
                secure=self.secure,
            )
        return self._client

    async def connect(self):
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
                logger.info(f"[MinioStorage] Created bucket: {self.bucket}")
            else:
                logger.info(f"[MinioStorage] Connected to bucket: {self.bucket}")
        except S3Error as e:
            logger.error(f"[MinioStorage] Failed to connect: {e}")
            raise

    async def upload_file(
        self,
        object_name: str,
        file_path: Path,
        content_type: str = "application/zip",
    ) -> Dict[str, Any]:
        try:
            self.client.fput_object(
                self.bucket,
                object_name,
                str(file_path),
                content_type=content_type,
            )
            logger.info(f"[MinioStorage] Uploaded: {object_name}")
            return {
                "status": "success",
                "object_name": object_name,
                "bucket": self.bucket,
            }
        except S3Error as e:
            logger.error(f"[MinioStorage] Upload failed: {e}")
            return {"status": "error", "error": str(e)}

    async def upload_data(
        self,
        object_name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> Dict[str, Any]:
        try:
            from io import BytesIO
            self.client.put_object(
                self.bucket,
                object_name,
                BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            logger.info(f"[MinioStorage] Uploaded data: {object_name}")
            return {
                "status": "success",
                "object_name": object_name,
                "size": len(data),
            }
        except S3Error as e:
            logger.error(f"[MinioStorage] Upload failed: {e}")
            return {"status": "error", "error": str(e)}

    async def download_file(
        self,
        object_name: str,
        file_path: Path,
    ) -> Dict[str, Any]:
        try:
            self.client.fget_object(
                self.bucket,
                object_name,
                str(file_path),
            )
            logger.info(f"[MinioStorage] Downloaded: {object_name}")
            return {
                "status": "success",
                "object_name": object_name,
                "file_path": str(file_path),
            }
        except S3Error as e:
            logger.error(f"[MinioStorage] Download failed: {e}")
            return {"status": "error", "error": str(e)}

    async def get_presigned_url(
        self,
        object_name: str,
        expires_seconds: int = 3600,
    ) -> str:
        try:
            from datetime import timedelta
            url = self.client.presigned_get_object(
                self.bucket,
                object_name,
                expires=timedelta(seconds=expires_seconds),
            )
            return url
        except S3Error as e:
            logger.error(f"[MinioStorage] Presigned URL failed: {e}")
            raise

    async def list_objects(self, prefix: str = "") -> list:
        try:
            objects = self.client.list_objects(
                self.bucket,
                prefix=prefix,
                recursive=True,
            )
            return [
                {"name": obj.object_name, "size": obj.size, "last_modified": obj.last_modified}
                for obj in objects
            ]
        except S3Error as e:
            logger.error(f"[MinioStorage] List objects failed: {e}")
            return []

    async def delete_object(self, object_name: str) -> Dict[str, Any]:
        try:
            self.client.remove_object(self.bucket, object_name)
            logger.info(f"[MinioStorage] Deleted: {object_name}")
            return {"status": "success", "object_name": object_name}
        except S3Error as e:
            logger.error(f"[MinioStorage] Delete failed: {e}")
            return {"status": "error", "error": str(e)}

    async def object_exists(self, object_name: str) -> bool:
        try:
            self.client.stat_object(self.bucket, object_name)
            return True
        except S3Error:
            return False

    async def get_object_info(self, object_name: str) -> Optional[Dict[str, Any]]:
        try:
            stat = self.client.stat_object(self.bucket, object_name)
            return {
                "name": stat.object_name,
                "size": stat.size,
                "content_type": stat.content_type,
                "last_modified": stat.last_modified,
            }
        except S3Error:
            return None

    async def delete_objects_by_prefix(self, prefix: str) -> Dict[str, Any]:
        """Delete all objects with the given prefix."""
        try:
            objects = self.client.list_objects(self.bucket, prefix=prefix, recursive=True)
            deleted = []
            errors = []
            for obj in objects:
                try:
                    self.client.remove_object(self.bucket, obj.object_name)
                    deleted.append(obj.object_name)
                    logger.info(f"[MinioStorage] Deleted: {obj.object_name}")
                except S3Error as e:
                    logger.error(f"[MinioStorage] Failed to delete {obj.object_name}: {e}")
                    errors.append({"object": obj.object_name, "error": str(e)})
            return {"status": "success", "deleted": deleted, "errors": errors, "count": len(deleted)}
        except S3Error as e:
            logger.error(f"[MinioStorage] Delete by prefix failed: {e}")
            return {"status": "error", "error": str(e)}