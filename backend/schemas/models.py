from sqlalchemy import Column, Integer, Text, TIMESTAMP, Numeric, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from database import Base

class Job(Base):
    __tablename__ = "jobs"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    submitter_email = Column(Text, nullable=False)
    status = Column(Text, nullable=False, server_default="queued")
    clip_duration_min_sec = Column(Integer, nullable=False)
    clip_duration_max_sec = Column(Integer, nullable=False)
    max_clips_per_video = Column(Integer, nullable=False)
    vertical_format = Column(Text, nullable=False)
    source_type = Column(Text, nullable=False)
    drive_folder_id = Column(Text, nullable=True)
    paused_reason = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    video_tasks = relationship("VideoTask", back_populates="job", cascade="all, delete-orphan")


class VideoTask(Base):
    __tablename__ = "video_tasks"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    job_id = Column(UUID(as_uuid=True), ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    source_ref = Column(Text, nullable=False)
    video_title = Column(Text, nullable=True)
    status = Column(Text, nullable=False, server_default="queued")
    worker_id = Column(Text, nullable=True)
    attempt_number = Column(Integer, nullable=False, server_default="0")
    heartbeat_at = Column(TIMESTAMP, nullable=True)
    duration_seconds = Column(Numeric(10, 2), nullable=True)
    codec = Column(Text, nullable=True)
    resolution = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    created_at = Column(TIMESTAMP, server_default=func.now())
    updated_at = Column(TIMESTAMP, server_default=func.now())

    job = relationship("Job", back_populates="video_tasks")
    clips = relationship("Clip", back_populates="video_task", cascade="all, delete-orphan")


class Clip(Base):
    __tablename__ = "clips"

    id = Column(UUID(as_uuid=True), primary_key=True, server_default=func.uuid_generate_v4())
    video_task_id = Column(UUID(as_uuid=True), ForeignKey("video_tasks.id", ondelete="CASCADE"), nullable=False)
    clip_index = Column(Integer, nullable=False)
    clip_key = Column(Text, nullable=False, unique=True)
    start_time_sec = Column(Numeric(10, 2), nullable=False)
    duration_sec = Column(Numeric(10, 2), nullable=False)
    end_time_sec = Column(Numeric(10, 2), nullable=False)
    status = Column(Text, nullable=False, server_default="planned")
    content_hash = Column(Text, nullable=True)
    drive_file_id = Column(Text, nullable=True)
    uploaded_at = Column(TIMESTAMP, nullable=True)

    video_task = relationship("VideoTask", back_populates="clips")