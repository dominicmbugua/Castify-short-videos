import os
from pathlib import Path
from typing import Optional, List
from datetime import datetime
import zipfile

import httpx
from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from uuid import UUID
from email_validator import validate_email, EmailNotValidError

from database import get_db
from schemas.models import Job, VideoTask
from object_storage import upload_to_staging, cleanup_scratch
from workers.tasks import process_job
from titles import title_from_url

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Local scratch space used only transiently while a file/ZIP is validated,
# before it's pushed to the object store and deleted from here.
SCRATCH_DIR = Path(__file__).resolve().parent.parent / "scratch"
SCRATCH_DIR.mkdir(exist_ok=True)

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


class JobDetail(BaseModel):
    id: UUID
    submitter_email: str
    status: str
    source_type: str
    vertical_format: str
    clip_duration_min_sec: int
    clip_duration_max_sec: int
    max_clips_per_video: int
    paused_reason: Optional[str]
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
        return "mp4_like"   # ISO base media 'ftyp' box — covers MP4 and MOV
    if header[:4] == b"\x1a\x45\xdf\xa3":
        return "matroska"   # EBML header — covers MKV and WebM
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
    """
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=URL_CHECK_TIMEOUT_SECONDS) as client:
            resp = await client.head(url)
            if resp.status_code >= 400:
                resp = await client.get(url, headers={"Range": "bytes=0-0"})
            if resp.status_code >= 400:
                return f"URL returned HTTP {resp.status_code}"
    except httpx.RequestError as e:
        return f"Could not reach URL ({e.__class__.__name__})"
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.post("", response_model=JobResponse, status_code=201)
async def create_job(
    db: Session = Depends(get_db),
    submitter_email: str = Form(...),
    clip_duration_sec: int = Form(...),
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

    if clip_duration_sec < 1:
        raise HTTPException(400, "clip_duration_sec must be at least 1")

    if max_clips_per_video < 1:
        raise HTTPException(400, "max_clips_per_video must be at least 1")

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

    # ---- create the job row ----
    # The DB still stores min/max columns; a fixed clip length is simply
    # min == max, so no schema change or worker change is needed.
    job = Job(
        submitter_email=submitter_email,
        clip_duration_min_sec=clip_duration_sec,
        clip_duration_max_sec=clip_duration_sec,
        max_clips_per_video=max_clips_per_video,
        vertical_format=vertical_format,
        source_type=source_type,
    )
    db.add(job)
    db.flush()  # populates job.id without committing yet

    # ---- Section 5.1: URL source needs no staging — the worker downloads
    # it directly later, so the VideoTask just records the URL as-is. ----
    if source_type == "url":
        video_task = VideoTask(
            job_id=job.id,
            source_ref=source_url,
            video_title=title_from_url(source_url),
        )
        db.add(video_task)

    # ---- Section 5.1: File/ZIP uploads are staged in the object store ----
    else:
        # The task must exist (and have an id) before staging, since the
        # object-store key is staging/{job_id}/{task_id}/source.{ext}.
        video_task = VideoTask(job_id=job.id, source_ref="pending")
        db.add(video_task)
        db.flush()  # populates video_task.id

        scratch_dir = SCRATCH_DIR / str(job.id) / str(video_task.id)
        scratch_dir.mkdir(parents=True, exist_ok=True)

        safe_name = os.path.basename(source_file.filename or "upload")
        local_path = scratch_dir / safe_name

        size = 0
        header_checked = False
        sniffed_type = None
        with open(local_path, "wb") as out:
            while chunk := await source_file.read(1024 * 1024):
                if not header_checked:
                    sniffed_type = sniff_file_type(chunk[:12])
                    if source_type == "file" and sniffed_type not in ("mp4_like", "matroska"):
                        out.close()
                        cleanup_scratch(scratch_dir)
                        db.rollback()
                        raise HTTPException(
                            400,
                            "File content doesn't look like a valid MP4/MOV/MKV video (magic-byte check failed)",
                        )
                    if source_type == "zip" and sniffed_type != "zip":
                        out.close()
                        cleanup_scratch(scratch_dir)
                        db.rollback()
                        raise HTTPException(
                            400,
                            "File content doesn't look like a valid ZIP archive (magic-byte check failed)",
                        )
                    header_checked = True

                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    cleanup_scratch(scratch_dir)
                    db.rollback()
                    raise HTTPException(413, "Uploaded file is too large")
                out.write(chunk)

        if source_type == "zip":
            zip_error = validate_zip_safety(local_path)
            if zip_error:
                cleanup_scratch(scratch_dir)
                db.rollback()
                raise HTTPException(400, zip_error)

        # ---- push the validated local file to the object store's staging
        # area; boto3 multipart-uploads larger files automatically ----
        ext = Path(safe_name).suffix.lstrip(".") or (
            "mp4" if sniffed_type == "mp4_like" else "mkv" if sniffed_type == "matroska" else "zip"
        )
        try:
            staged_key = upload_to_staging(local_path, job.id, video_task.id, ext)
        except Exception as e:
            cleanup_scratch(scratch_dir)
            db.rollback()
            raise HTTPException(502, f"Failed to stage upload in object storage: {e}")

        cleanup_scratch(scratch_dir)  # now durably in the object store

        video_task.source_ref = staged_key
        video_task.video_title = safe_name

    db.commit()
    db.refresh(job)

    # ---- Section: task enqueueing — hand the job off to a Celery worker ----
    process_job.delay(str(job.id))

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


@router.get("/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = (
        db.query(Job)
        .options(joinedload(Job.video_tasks))
        .filter(Job.id == job_id)
        .first()
    )
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.get("/{job_id}/tasks", response_model=List[VideoTaskSummary])
def get_job_tasks(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    tasks = db.query(VideoTask).filter(VideoTask.job_id == job_id).all()
    return tasks