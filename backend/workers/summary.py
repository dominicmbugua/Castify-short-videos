from datetime import date


def submission_folder_name(job) -> str:
    """Section 8.1's folder naming: {job_id}_{email_local_part}_{date}"""
    local_part = job.submitter_email.split("@")[0]
    date_str = job.created_at.strftime("%Y-%m-%d") if job.created_at else date.today().isoformat()
    return f"{job.id}_{local_part}_{date_str}"


def build_submission_summary(job, video_tasks) -> dict:
    """
    Section 5.3 / 11.4 — per-video outcome breakdown for the summary
    email and the submission_summary.json uploaded to the Drive root.
    """
    videos = []
    for vt in video_tasks:
        videos.append({
            "video_task_id": str(vt.id),
            "video_title": vt.video_title,
            "status": vt.status,
            "failure_reason": vt.failure_reason,
            "duration_seconds": float(vt.duration_seconds) if vt.duration_seconds else None,
            "clips": [
                {
                    "clip_index": c.clip_index,
                    "start_time_sec": float(c.start_time_sec),
                    "duration_sec": float(c.duration_sec),
                    "status": c.status,
                    "drive_file_id": c.drive_file_id,
                }
                for c in sorted(vt.clips, key=lambda c: c.clip_index)
            ],
        })

    return {
        "job_id": str(job.id),
        "submitter_email": job.submitter_email,
        "status": job.status,
        "vertical_format": job.vertical_format,
        "videos": videos,
    }