"""
Document Storage Service.

Production: uploads to AWS S3 with server-side AES-256 encryption.
Development: saves to local disk under local_uploads/.

The application server never retains the file permanently -- it reads the bytes, upload, and discards. Only the S3 key (or local path) is stored in the database.

Presigned URLs:
    Ops agents access the documents via time-limited presigned URLs (1 hour).
    This means even if someone intercepts the URL, it expires quickly.
    The raw S3 bucket is never publicly accessible.
"""

import uuid, logging
from pathlib import Path
from fastapi import UploadFile
from config import settings

logger = logging.getLogger(__name__)

LOCAL_DIR = Path("local_uploads")
LOCAL_DIR.mkdir(exist_ok=True)


class StorageService:

    async def upload(self, file: UploadFile, application_id: str, document_type: str) -> dict:
        """
        Uploads a file. Returns storage metadata dict:
        {
            "s3_key":       str | None,
            "local_path":   str | None,
            "storage":      "s3" | "local",
        }
        """
        ext = file.filename.rsplit(".", 1)[-1].lower()
        unique_name = f"{uuid.uuid4()}.{ext}"
        file_content = await file.read()

        if settings.USE_AWS_S3:
            return await self._upload_s3(file_content, file.content_type, file.filename, application_id, document_type, unique_name)
        return self._upload_local(file_content, application_id, document_type, unique_name)

    async def _upload_s3(self, content: bytes, content_type: str, original_name: str, application_id: str, document_type: str, unique_name: str) -> dict:
        """
        Uploads to S3 with:
            - Server-side AES-256 encryption (SSE-S3)
            - Metadata tagging for auditability
            - Private ACL -- never public
            
        S3 key structure: kyc/{application_id}/{document_type}/{uuid}.ext
        This structure makes it easy to list all the docs for an application and to set S3 lifecycle rules per document type.
        """
        import boto3
        s3_key = f"kyc/{application_id}/{document_type}/{unique_name}"

        s3 = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        s3.put_object(
            Bucket=settings.S3_BUCKET_NAME,
            Key=s3_key,
            Body=content,
            ContentType=content_type,
            ServerSideEncryption="AES256",  # Encrypting at rest
            Metadata={
                "application-id": application_id,
                "document-type": document_type,
                "original-name": original_name,
            },
        )
        logger.info(f"Uploaded to S3: {s3_key}")
        return {"s3_key": s3_key, "local_path": None, "storage": "s3"}

    def _upload_local(self, content: bytes, application_id: str, document_type: str, unique_name: str) -> dict:
        dest_dir = LOCAL_DIR / application_id / document_type
        dest_dir.mkdir(parents=True, exist_ok=True)
        path = dest_dir / unique_name
        path.write_bytes(content)
        logger.info(f"Saved locally: {path}")
        return {"s3_key": None, "local_path": str(path), "storage": "local"}

    def generate_presigned_url(self, s3_key: str, expiry_seconds: int = 3600) -> str:
        """
        Generates a time-limited presigned URL for ops to download the document. The file itself is never served through our API -- we redirect ops to S3.
        """
        if not settings.USE_AWS_S3:
            return f"http://localhost:8001/local-file/{s3_key}"

        import boto3
        s3 = boto3.client(
            "s3",
            region_name=settings.AWS_REGION,
            aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
        )
        return s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": settings.S3_BUCKET_NAME, "Key": s3_key},
            ExpiresIn=expiry_seconds,
        )

