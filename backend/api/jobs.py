from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, EmailStr, field_validator
from uuid import UUID
from database import get_db
from schemas.models import Job

router = APIRouter(prefix="/jobs", tags=["jobs"])

class JobCreate(BaseModel):
    submitter_email: EmailStr
    clip_duration_min_sec: int
    clip_duration_max_sec: int
    max_clips_per_video: int
    vertical_format: str  # center_crop | pad_canvas
    source_type: str      # url | file | zip

    @field_validator("vertical_format")
    def check_vertical_format(cls, v):
        if v not in ("center_crop", "pad_canvas"):
            raise ValueError("vertical_format must be center_crop or pad_canvas")
        return v

    @field_validator("source_type")
    def check_source_type(cls, v):
        if v not in ("url", "file", "zip"):
            raise ValueError("source_type must be url, file, or zip")
        return v

class JobResponse(BaseModel):
    id: UUID
    status: str
    class Config:
        from_attributes = True

@router.post("", response_model=JobResponse, status_code=201)
def create_job(payload: JobCreate, db: Session = Depends(get_db)):
    if payload.clip_duration_max_sec < payload.clip_duration_min_sec:
        raise HTTPException(400, "clip_duration_max_sec must be >= clip_duration_min_sec")

    job = Job(
        submitter_email=payload.submitter_email,
        clip_duration_min_sec=payload.clip_duration_min_sec,
        clip_duration_max_sec=payload.clip_duration_max_sec,
        max_clips_per_video=payload.max_clips_per_video,
        vertical_format=payload.vertical_format,
        source_type=payload.source_type,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job

@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: str, db: Session = Depends(get_db)):
    job = db.query(Job).filter(Job.id == job_id).first()
    if not job:
        raise HTTPException(404, "Job not found")
    return job