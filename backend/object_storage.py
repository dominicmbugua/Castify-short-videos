import os
import shutil
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / "config" / "development.env")

S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:9000")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "minioadmin")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "minioadmin_dev")
S3_BUCKET = os.getenv("S3_BUCKET", "castify-dev")
S3_REGION = os.getenv("S3_REGION", "us-east-1")

# Section 5.2: incomplete multipart uploads older than this are auto-aborted
# by the object store itself. Safe to time-box aggressively since nothing
# incomplete is ever referenced by a Job.
INCOMPLETE_UPLOAD_LIFETIME_DAYS = 1


def get_s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        region_name=S3_REGION,
        config=Config(signature_version="s3v4"),
    )


def ensure_bucket_exists() -> None:
    s3 = get_s3_client()
    try:
        s3.head_bucket(Bucket=S3_BUCKET)
    except ClientError:
        s3.create_bucket(Bucket=S3_BUCKET)


def ensure_incomplete_upload_lifecycle_rule() -> None:
    """
    Section 5.2 — abort incomplete multipart uploads automatically.
    This is a nice-to-have cleanup rule, not something the app depends on
    to function, so a failure here logs a warning rather than blocking
    startup entirely.
    """
    s3 = get_s3_client()
    try:
        s3.put_bucket_lifecycle_configuration(
            Bucket=S3_BUCKET,
            LifecycleConfiguration={
                "Rules": [
                    {
                        "ID": "abort-incomplete-multipart-uploads",
                        "Status": "Enabled",
                        "Filter": {},
                        "AbortIncompleteMultipartUpload": {
                            "DaysAfterInitiation": INCOMPLETE_UPLOAD_LIFETIME_DAYS
                        },
                    }
                ]
            },
        )
    except ClientError as e:
        print(
            f"[object_storage] Warning: could not set bucket lifecycle rule ({e}). "
            "Incomplete multipart uploads won't be auto-cleaned by the store, "
            "but this doesn't block the app from running."
        )


def staging_key(job_id, task_id, ext: str) -> str:
    """Section 5.1's key convention: staging/{job_id}/{task_id}/source.{ext}"""
    return f"staging/{job_id}/{task_id}/source.{ext.lstrip('.')}"


def upload_to_staging(local_path: Path, job_id, task_id, ext: str) -> str:
    """
    Pushes a locally-validated file to the staging area. boto3's upload_file
    automatically performs a real S3 multipart upload for larger files,
    retrying individual failed parts (Section 5.2) rather than restarting
    the whole transfer. Returns the object key.
    """
    key = staging_key(job_id, task_id, ext)
    s3 = get_s3_client()
    s3.upload_file(str(local_path), S3_BUCKET, key)
    return key


def cleanup_scratch(scratch_dir: Path) -> None:
    """Removes the local scratch copy once it's durably staged (or after a
    failed validation) — the file no longer needs to live on the API
    server's disk once it's in the object store."""
    shutil.rmtree(scratch_dir, ignore_errors=True)
    try:
        scratch_dir.parent.rmdir()
    except OSError:
        pass