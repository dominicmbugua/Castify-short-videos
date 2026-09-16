import os
import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Form, File, UploadFile
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from uuid import UUID

from database import get_db
from schemas.models import Job, VideoTask

router = APIRouter(prefix="/jobs", tags=["jobs"])

UPLOAD_DIR = Path(__file__).resolve().parent.parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

EMAIL_RE = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/x-matroska"}
ALLOWED_ZIP_TYPES = {"application/zip", "application/x-zip-compressed"}
MAX_UPLOAD_BYTES = 2 * 1024 * 1024 * 1024  # 2GB — adjust to taste


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
    # ---- validation ----
    if not EMAIL_RE.match(submitter_email):
        raise HTTPException(400, "submitter_email must be a valid email address")

    if vertical_format not in ("center_crop", "pad_canvas"):
        raise HTTPException(400, "vertical_format must be center_crop or pad_canvas")

    if source_type not in ("url", "file", "zip"):
        raise HTTPException(400, "source_type must be url, file, or zip")

    if clip_duration_max_sec < clip_duration_min_sec:
        raise HTTPException(400, "clip_duration_max_sec must be >= clip_duration_min_sec")

    if source_type == "url":
        if not source_url or not source_url.strip():
            raise HTTPException(400, "source_url is required when source_type is 'url'")
    else:
        if source_file is None:
            raise HTTPException(400, f"source_file is required when source_type is '{source_type}'")
        if source_type == "file" and source_file.content_type not in ALLOWED_VIDEO_TYPES:
            raise HTTPException(400, "source_file must be an MP4, MOV, or MKV video")
        if source_type == "zip" and source_file.content_type not in ALLOWED_ZIP_TYPES:
            raise HTTPException(400, "source_file must be a ZIP archive")

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

    # ---- resolve source_ref, saving the upload to disk if needed ----
    if source_type == "url":
        source_ref = source_url.strip()
        video_title = None
    else:
        job_upload_dir = UPLOAD_DIR / str(job.id)
        job_upload_dir.mkdir(parents=True, exist_ok=True)

        safe_name = os.path.basename(source_file.filename or "upload")
        dest_path = job_upload_dir / safe_name

        size = 0
        with open(dest_path, "wb") as out:
            while chunk := await source_file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    out.close()
                    dest_path.unlink(missing_ok=True)
                    db.rollback()
                    raise HTTPException(413, "Uploaded file is too large")
                out.write(chunk)

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