import os
import zipfile
from pathlib import Path
from typing import Optional, List
from datetime import datetime

import httpx
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from uuid import UUID
from email_validator import validate_email, EmailNotValidError

from database import get_db
from schemas.models import Job, VideoTask

router = APIRouter(prefix="/jobs", tags=["jobs"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024       # 2GB per file — adjust to taste
MAX_ZIP_ENTRIES = 20                            # matches the UI's stated "max 20" hint
MAX_ZIP_UNCOMPRESSED_TOTAL = 5 * 1024 * 1024 * 1024  # 5GB total once extracted
MAX_ZIP_COMPRESSION_RATIO = 100                 # flags likely zip bombs
URL_CHECK_TIMEOUT_SECONDS = 8.0


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class JobResponse(BaseModel):
    id: UUID
    status: str
    class Config:
        from_attributes = True


class VideoTaskSummary(BaseModel):
    id: UUID
    video_title: Optional[str]
    source_ref: str
    status: str
    class Config:
        from_attributes = True


class JobListItem(BaseModel):
    id: UUID
    submitter_email: str
    status: str
    source_type: str
    vertical_format: str
    created_at: datetime
    video_tasks: List[VideoTaskSummary]
    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def sniff_file_type(header: bytes) -> str:
    """
    Identify a file by its actual leading bytes rather than trusting the
    browser-supplied content-type header, which can be wrong or spoofed.
    Returns 'mp4_like', 'matroska', 'zip', or 'unknown'.
    """
    if len(header) >= 8 and header[4:8] == b"ftyp":
        # ISO base media file format 'ftyp' box — covers both MP4 and MOV
        return "mp4_like"
    if header[:4] == b"\x1a\x45\xdf\xa3":
        # EBML header — covers MKV and WebM
        return "matroska"
    if header[:4] in (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"):
        return "zip"
    return "unknown"


def validate_zip_safety(path: Path) -> Optional[str]:
    """
    Runs safety checks on a saved ZIP file. Returns an error message string
    if the archive is unsafe, or None if it passes.
    """
    try:
        with zipfile.ZipFile(path) as zf:
            bad_entry = zf.testzip()
            if bad_entry is not None:
                return f"ZIP archive is corrupted (bad entry: {bad_entry})"

            infos = zf.infolist()
            if len(infos) == 0:
                return "ZIP archive is empty"
            if len(infos) > MAX_ZIP_ENTRIES:
                return f"ZIP archive has {len(infos)} entries, exceeding the max of {MAX_ZIP_ENTRIES}"

            total_uncompressed = 0
            for info in infos:
                normalized = os.path.normpath(info.filename)
                if normalized.startswith("..") or os.path.isabs(normalized):
                    return f"ZIP contains an unsafe path: {info.filename}"

                total_uncompressed += info.file_size
                if info.compress_size > 0:
                    ratio = info.file_size / info.compress_size
                    if ratio > MAX_ZIP_COMPRESSION_RATIO:
                        return f"ZIP entry '{info.filename}' has a suspicious compression ratio (possible zip bomb)"

            if total_uncompressed > MAX_ZIP_UNCOMPRESSED_TOTAL:
                return "ZIP archive's uncompressed contents exceed the size limit"

    except zipfile.BadZipFile:
        return "File is not a valid ZIP archive"

    return None


async def check_url_reachable(url: str) -> Optional[str]:
    """
    Confirms a source URL actually resolves and responds. Deliberately does
    NOT require a video content-type — pages like a YouTube watch URL return
    text/html but are still valid sources a worker will fetch later.
    Returns an error message if unreachable, or None if it's fine.
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=URL_CHECK_TIMEOUT_SECONDS) as client:
            resp = await client.head(url)
            if resp.status_code >= 400:
                # some servers don't implement HEAD properly — retry with a ranged GET
                resp = await client.get(url, headers={"Range": "bytes=0-0"})
            if resp.status_code >= 400:
                return f"URL returned HTTP {resp.status_code}"
    except httpx.RequestError as e:
        return f"Could not reach URL ({e.__class__.__name__})"
    return None


def _cleanup_upload(dest_path: Path, job_upload_dir: Path) -> None:
    dest_path.unlink(missing_ok=True)
    try:
        job_upload_dir.rmdir()
    except OSError:
        pass  # directory not empty or already gone — safe to ignore


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    db: Session = Depends(get_db),
    submitter_email: str = Form(...),
    clip_duration_min_sec: int = Form(...),
    clip_duration_max_sec: int = Form(...),
    max_clips_per_video: int = Form(...),
    vertical_format: str = Form(...),
    source_type: str = Form(...),
    source_url: Optional[str] = Form(None),
    source_file: Optional[UploadFile] = File(None),
):
    # ---- basic field validation ----
    try:
        submitter_email = validate_email(submitter_email, check_deliverability=False).normalized
    except EmailNotValidError as e:
        raise HTTPException(400, f"submitter_email is invalid: {str(e)}")

    if vertical_format not in ("center_crop", "pad_canvas"):
        raise HTTPException(400, "vertical_format must be center_crop or pad_canvas")

    if source_type not in ("url", "file", "zip"):
        raise HTTPException(400, "source_type must be url, file, or zip")

    if clip_duration_max_sec < clip_duration_min_sec:
        raise HTTPException(400, "clip_duration_max_sec must be >= clip_duration_min_sec")

    # ---- source-specific pre-checks (before touching the database) ----
    if source_type == "url":
        if not source_url or not source_url.strip():
            raise HTTPException(400, "source_url is required when source_type is 'url'")
        source_url = source_url.strip()
        url_error = await check_url_reachable(source_url)
        if url_error:
            raise HTTPException(400, f"source_url is not reachable: {url_error}")
    else:
        if source_file is None:
            raise HTTPException(400, f"source_file is required when source_type is '{source_type}'")

    # ---- create the job row first, so we have an id to namespace the upload ----
    job = Job(
        submitter_email=submitter_email,
        clip_duration_min_sec=clip_duration_min_sec,
        clip_duration_max_sec=clip_duration_max_sec,
        max_clips_per_video=max_clips_per_video,
        vertical_format=vertical_format,
        source_type=source_type,
    )
    db.add(job)
    db.flush()  # populates job.id without committing yet

    # ---- resolve source_ref ----
    if source_type == "url":
        source_ref = source_url
        video_title = None
    else:
        job_upload_dir = UPLOAD_DIR / str(job.id)
        job_upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = os.path.basename(source_file.filename or "upload")
        dest_path = job_upload_dir / safe_name

        size = 0
        header_checked = False
        with open(dest_path, "wb") as out:
            while chunk := await source_file.read(1024 * 1024):
                if not header_checked:
                    sniffed = sniff_file_type(chunk[:12])
                    if source_type == "file" and sniffed not in ("mp4_like", "matroska"):
                        out.close()
                        _cleanup_upload(dest_path, job_upload_dir)
                        db.rollback()
                        raise HTTPException(
                            400,
                            "File content doesn't look like a valid MP4/MOV/MKV video (magic-byte check failed)",
                        )
                    if source_type == "zip" and sniffed != "zip":
                        out.close()
                        _cleanup_upload(dest_path, job_upload_dir)
                        db.rollback()
                        raise HTTPException(
                            400,
                            "File content doesn't look like a valid ZIP archive (magic-byte check failed)",
                        )
                    header_checked = True

                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    _cleanup_upload(dest_path, job_upload_dir)
                    db.rollback()
                    raise HTTPException(413, "Uploaded file is too large")
                out.write(chunk)

        if source_type == "zip":
            zip_error = validate_zip_safety(dest_path)
            if zip_error:
                _cleanup_upload(dest_path, job_upload_dir)
                db.rollback()
                raise HTTPException(400, zip_error)

        source_ref = str(dest_path)
        video_title = safe_name

    video_task = VideoTask(
        job_id=job.id,
        source_ref=source_ref,
        video_title=video_title,
    )
    db.add(video_task)

    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=List[JobListItem])
def list_jobs(db: Session = Depends(get_db), limit: int = 50):
    jobs = (
        db.query(Job)
        .options(joinedload(Job.video_tasks))
        .order_by(Job.created_at.desc())
        .limit(limit)
        .all()
    )
    return jobs


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return job