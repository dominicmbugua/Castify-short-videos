import json
import shutil
from pathlib import Path
from datetime import datetime, timezone

from workers.celery_app import celery_app
from database import SessionLocal
from schemas.models import Job, VideoTask, Clip
from workers.video_inspection import download_source_to_scratch, inspect_video, generate_clip_plan
from workers.clip_extraction import extract_and_format_clip, compute_content_hash
from workers.drive_upload import upload_file
from workers.summary import submission_folder_name, build_submission_summary

WORKER_SCRATCH_DIR = Path(__file__).resolve().parent.parent / "worker_scratch"
WORKER_SCRATCH_DIR.mkdir(exist_ok=True)


def _process_video_task(db, job, vt, task_scratch):
    """Runs one VideoTask through downloading -> inspecting -> planning ->
    extracting -> uploading. Returns True if at least one clip succeeded."""

    vt.status = "downloading"
    db.commit()
    local_path = download_source_to_scratch(vt, job.source_type, task_scratch)

    vt.status = "inspecting"
    db.commit()
    info = inspect_video(local_path)
    vt.duration_seconds = info["duration_sec"]
    vt.codec = info["codec"]
    vt.resolution = info["resolution"]
    db.commit()

    plan = generate_clip_plan(
        duration_sec=info["duration_sec"],
        min_sec=job.clip_duration_min_sec,
        max_sec=job.clip_duration_max_sec,
        max_clips=job.max_clips_per_video,
    )

    if not plan:
        vt.status = "no_clips_too_short"
        db.commit()
        print(f"[worker]   task {vt.id}: too short for any clips ({info['duration_sec']:.1f}s)")
        return True  # not a failure — a valid terminal outcome

    clips = []
    for i, (start, duration) in enumerate(plan):
        clip = Clip(
            video_task_id=vt.id,
            clip_index=i,
            clip_key=f"{vt.id}:{i}",
            start_time_sec=start,
            duration_sec=duration,
            end_time_sec=start + duration,
            status="planned",
        )
        db.add(clip)
        clips.append(clip)
    db.commit()
    print(f"[worker]   task {vt.id}: planned {len(clips)} clip(s)")

    vt.status = "extracting"
    db.commit()

    clips_dir = task_scratch / "clips"
    clips_dir.mkdir(exist_ok=True)

    for clip in clips:
        try:
            out_path = clips_dir / f"clip_{clip.clip_index:03d}.mp4"
            extract_and_format_clip(
                local_path, out_path,
                start_sec=float(clip.start_time_sec),
                duration_sec=float(clip.duration_sec),
                vertical_format=job.vertical_format,
            )
            clip.content_hash = compute_content_hash(out_path)
            clip.status = "extracted"
            db.commit()
        except Exception as e:
            clip.status = "failed"
            db.commit()
            print(f"[worker]     clip {clip.clip_index}: extraction FAILED — {e}")

    vt.status = "uploading"
    db.commit()

    folder_path = [submission_folder_name(job), vt.video_title or f"video_{vt.id}"]
    any_uploaded = False

    for clip in clips:
        if clip.status != "extracted":
            continue
        try:
            local_clip_path = clips_dir / f"clip_{clip.clip_index:03d}.mp4"
            file_id = upload_file(
                local_clip_path, folder_path,
                filename=f"clip_{clip.clip_index:03d}.mp4",
                clip_key=clip.clip_key,
                content_hash=clip.content_hash or "",
            )
            clip.drive_file_id = file_id
            clip.uploaded_at = datetime.now(timezone.utc)
            clip.status = "uploaded"
            db.commit()
            any_uploaded = True
        except Exception as e:
            clip.status = "failed"
            db.commit()
            print(f"[worker]     clip {clip.clip_index}: upload FAILED — {e}")

    if any_uploaded:
        vt.status = "completed"
        db.commit()
        return True
    else:
        vt.status = "failed"
        vt.failure_reason = "All clips failed extraction or upload"
        db.commit()
        return False


@celery_app.task(name="process_job")
def process_job(job_id: str):
    db = SessionLocal()
    try:
        job = db.query(Job).filter(Job.id == job_id).first()
        if not job:
            print(f"[worker] Job {job_id} not found — nothing to do")
            return

        job.status = "processing"
        db.commit()

        video_tasks = db.query(VideoTask).filter(VideoTask.job_id == job_id).all()
        print(f"[worker] Job {job.id}: processing {len(video_tasks)} video task(s)")

        outcomes = []
        for vt in video_tasks:
            task_scratch = WORKER_SCRATCH_DIR / str(job.id) / str(vt.id)

            if job.source_type == "zip":
                vt.status = "failed"
                vt.failure_reason = "ZIP expansion into individual video tasks isn't implemented yet"
                db.commit()
                outcomes.append(False)
                print(f"[worker]   task {vt.id}: skipped — ZIP expansion not yet implemented")
                continue

            try:
                ok = _process_video_task(db, job, vt, task_scratch)
                outcomes.append(ok)
            except Exception as e:
                db.rollback()
                vt.status = "failed"
                vt.failure_reason = str(e)[:500]
                db.commit()
                outcomes.append(False)
                print(f"[worker]   task {vt.id}: FAILED — {e}")
            finally:
                shutil.rmtree(task_scratch, ignore_errors=True)

        if all(outcomes):
            job.status = "completed"
        elif any(outcomes):
            job.status = "completed_partial"
        else:
            job.status = "failed"
        db.commit()

        # submission_summary.json — Zawadi's Day 5 item
        video_tasks = db.query(VideoTask).filter(VideoTask.job_id == job_id).all()
        summary = build_submission_summary(job, video_tasks)
        summary_dir = WORKER_SCRATCH_DIR / str(job.id)
        summary_dir.mkdir(parents=True, exist_ok=True)
        summary_path = summary_dir / "submission_summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2)

        upload_file(
            summary_path,
            [submission_folder_name(job)],
            filename="submission_summary.json",
            clip_key=f"{job.id}:summary",
            mimetype="application/json",
        )
        shutil.rmtree(summary_dir, ignore_errors=True)

        print(f"[worker] Job {job.id}: complete (status={job.status})")

    finally:
        db.close()