-- Castify Shorts Pipeline — Initial Schema (Day 1)
-- PostgreSQL 13+

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Job: top-level submission
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    submitter_email TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued' 
        CHECK (status IN (
            'queued', 'validating', 'processing', 'uploading', 
            'completed', 'completed_partial', 'failed', 
            'paused_drive_quota', 'completed_email_failed'
        )),
    clip_duration_min_sec INTEGER NOT NULL,
    clip_duration_max_sec INTEGER NOT NULL,
    max_clips_per_video INTEGER NOT NULL,
    vertical_format TEXT NOT NULL CHECK (vertical_format IN ('center_crop', 'pad_canvas')),
    source_type TEXT NOT NULL CHECK (source_type IN ('url', 'file', 'zip')),
    drive_folder_id TEXT,
    paused_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_job_email ON jobs (submitter_email);
CREATE INDEX idx_job_status ON jobs (status);

-- Video Task: one per video in the job
CREATE TABLE video_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_ref TEXT NOT NULL,
    video_title TEXT,
    status TEXT NOT NULL DEFAULT 'queued'
        CHECK (status IN (
            'queued', 'downloading', 'inspecting', 'planning', 
            'extracting', 'encoding', 'uploading', 'completed', 
            'no_clips_too_short', 'failed'
        )),
    worker_id TEXT,
    attempt_number INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TIMESTAMP,
    duration_seconds NUMERIC(10, 2),
    codec TEXT,
    resolution TEXT,
    failure_reason TEXT,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_task_job ON video_tasks (job_id);
CREATE INDEX idx_task_status ON video_tasks (status);

-- Clip: individual extracted segment
CREATE TABLE clips (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    video_task_id UUID NOT NULL REFERENCES video_tasks(id) ON DELETE CASCADE,
    clip_index INTEGER NOT NULL,
    clip_key TEXT NOT NULL UNIQUE,
    start_time_sec NUMERIC(10, 2) NOT NULL,
    duration_sec NUMERIC(10, 2) NOT NULL,
    end_time_sec NUMERIC(10, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'planned'
        CHECK (status IN ('planned', 'extracted', 'uploaded', 'failed')),
    content_hash TEXT,
    drive_file_id TEXT,
    uploaded_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_clip_task ON clips (video_task_id);
CREATE INDEX idx_clip_status ON clips (status);

-- Email Delivery: tracked separately from Job
CREATE TABLE email_deliveries (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    attempt_number INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'send_attempted'
        CHECK (status IN ('send_attempted', 'sent', 'confirmed', 'failed')),
    provider_message_id TEXT,
    sent_at TIMESTAMP,
    confirmed_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_delivery_job ON email_deliveries (job_id);
CREATE INDEX idx_delivery_status ON email_deliveries (status);

-- Auto-update timestamp trigger
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER jobs_update_trigger BEFORE UPDATE ON jobs FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER video_tasks_update_trigger BEFORE UPDATE ON video_tasks FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER clips_update_trigger BEFORE UPDATE ON clips FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
CREATE TRIGGER email_deliveries_update_trigger BEFORE UPDATE ON email_deliveries FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();