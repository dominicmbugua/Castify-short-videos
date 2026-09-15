from sqlalchemy import Column, Integer, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID
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