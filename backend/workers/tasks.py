from workers.celery_app import celery_app
from database import SessionLocal
from schemas.models import Job, VideoTask


@celery_app.task(name="process_job")
def process_job(job_id: str):
    """
    Day 3 stub — proves task enqueueing works end to end. Fetches the Job
    and its VideoTasks and logs what it found, then marks the job as
    'validating' so it's visible from the dashboard/status page that a
    worker actually picked it up. Real download/clip/upload logic
    (Section 6) replaces this later.
    """
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            print(f"[worker] Job {job_id} not found — nothing to do")
            return

        tasks = db.query(VideoTask).filter(VideoTask.job_id == job_id).all()
        print(f"[worker] Picked up job {job.id} ({job.source_type}, {len(tasks)} video task(s))")
        for t in tasks:
            print(f"[worker]   - task {t.id}: {t.source_ref}")

        job.status = "validating"
        db.commit()
        print(f"[worker] Job {job.id} marked as validating")
    finally:
        db.close()