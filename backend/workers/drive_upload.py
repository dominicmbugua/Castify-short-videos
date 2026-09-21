import os
import uuid
from pathlib import Path
from typing import List
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / "config" / "development.env")

GOOGLE_SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
GOOGLE_DRIVE_FOLDER_ID = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()

DRIVE_ENABLED = bool(GOOGLE_SERVICE_ACCOUNT_JSON and GOOGLE_DRIVE_FOLDER_ID)

if not DRIVE_ENABLED:
    print(
        "[drive_upload] No GOOGLE_SERVICE_ACCOUNT_JSON / GOOGLE_DRIVE_FOLDER_ID set — "
        "using a local STUB uploader until real credentials are added."
    )


def _stub_upload(local_path: Path, clip_key: str) -> str:
    """
    Pretends to upload. Returns a fake drive_file_id so dedup checks,
    status transitions, and submission_summary.json all behave exactly
    as they will once real credentials are added — only this function's
    body changes at that point.
    """
    fake_id = f"stub-{uuid.uuid4()}"
    print(f"[drive_upload] STUB uploaded {local_path.name} ({clip_key}) -> {fake_id}")
    return fake_id


def _ensure_folder_path(drive, root_id: str, path_parts: List[str]) -> str:
    parent_id = root_id
    for part in path_parts:
        safe_part = part.replace("'", "\\'")
        query = (
            f"'{parent_id}' in parents and trashed = false and name = '{safe_part}' "
            f"and mimeType = 'application/vnd.google-apps.folder'"
        )
        found = drive.files().list(q=query, fields="files(id)").execute().get("files", [])
        if found:
            parent_id = found[0]["id"]
        else:
            folder = drive.files().create(
                body={
                    "name": part,
                    "parents": [parent_id],
                    "mimeType": "application/vnd.google-apps.folder",
                },
                fields="id",
            ).execute()
            parent_id = folder["id"]
    return parent_id


def _real_upload(
    local_path: Path,
    drive_folder_path: List[str],
    filename: str,
    clip_key: str,
    content_hash: str,
    mimetype: str,
) -> str:
    """Section 8.3 — real Drive upload with appProperties-based dedup."""
    import json
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload

    creds_info = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
    creds = service_account.Credentials.from_service_account_info(
        creds_info, scopes=["https://www.googleapis.com/auth/drive"]
    )
    drive = build("drive", "v3", credentials=creds)

    parent_id = _ensure_folder_path(drive, GOOGLE_DRIVE_FOLDER_ID, drive_folder_path)

    query = (
        f"'{parent_id}' in parents and trashed = false "
        f"and appProperties has {{ key='clip_key' and value='{clip_key}' }}"
    )
    existing = drive.files().list(q=query, fields="files(id)").execute().get("files", [])
    if existing:
        return existing[0]["id"]

    media = MediaFileUpload(str(local_path), mimetype=mimetype, resumable=True)
    file_metadata = {
        "name": filename,
        "parents": [parent_id],
        "appProperties": {"clip_key": clip_key, "content_hash": content_hash},
    }
    created = drive.files().create(body=file_metadata, media_body=media, fields="id").execute()
    return created["id"]


def upload_file(
    local_path: Path,
    drive_folder_path: List[str],
    filename: str,
    clip_key: str,
    content_hash: str = "",
    mimetype: str = "video/mp4",
) -> str:
    """
    Public entry point used by the worker. Uses the real Drive
    implementation once credentials are set; otherwise falls back to
    the stub so the rest of the pipeline is fully testable today.
    """
    if DRIVE_ENABLED:
        return _real_upload(local_path, drive_folder_path, filename, clip_key, content_hash, mimetype)
    return _stub_upload(local_path, clip_key)