import random
from pathlib import Path

import httpx
import ffmpeg

from object_storage import get_s3_client, S3_BUCKET


def download_source_to_scratch(video_task, job_source_type: str, scratch_dir: Path) -> Path:
    """
    Downloads a VideoTask's source into local worker scratch space so
    ffprobe/ffmpeg can operate on it. URL sources are fetched directly
    (Section 5.1 — no staging involved for these); file sources are pulled
    from their staged object-store key.
    """
    scratch_dir.mkdir(parents=True, exist_ok=True)
    dest = scratch_dir / "source"

    if job_source_type == "url":
        with httpx.stream("GET", video_task.source_ref, follow_redirects=True, timeout=60.0) as r:
            r.raise_for_status()
            with open(dest, "wb") as f:
                for chunk in r.iter_bytes(1024 * 1024):
                    f.write(chunk)
    else:
        s3 = get_s3_client()
        s3.download_file(S3_BUCKET, video_task.source_ref, str(dest))

    return dest


def inspect_video(path: Path) -> dict:
    """
    Section 2.2 — ffprobe-based background inspection. Returns the video's
    duration (seconds), video codec name, and "WxH" resolution.
    """
    probe = ffmpeg.probe(str(path))
    video_streams = [s for s in probe.get("streams", []) if s.get("codec_type") == "video"]
    if not video_streams:
        raise ValueError("No video stream found in source file")

    stream = video_streams[0]
    duration = float(probe.get("format", {}).get("duration") or stream.get("duration") or 0)
    codec = stream.get("codec_name", "unknown")
    width = stream.get("width")
    height = stream.get("height")
    resolution = f"{width}x{height}" if width and height else "unknown"

    return {"duration_sec": duration, "codec": codec, "resolution": resolution}


def generate_clip_plan(
    duration_sec: float,
    min_sec: int,
    max_sec: int,
    max_clips: int,
    max_attempts: int = 200,
) -> list[tuple[float, float]]:
    """
    Section 3 — random clip-plan generator. Returns up to max_clips
    (start_time_sec, duration_sec) tuples, chronologically sorted and
    guaranteed non-overlapping. Returns an empty list if the video is too
    short for even one clip (short-video handling).
    """
    if duration_sec < min_sec:
        return []

    clips: list[tuple[float, float]] = []
    attempts = 0

    while len(clips) < max_clips and attempts < max_attempts:
        attempts += 1
        longest_possible = min(max_sec, duration_sec)
        if longest_possible < min_sec:
            break

        clip_duration = random.uniform(min_sec, longest_possible)
        latest_start = duration_sec - clip_duration
        if latest_start < 0:
            continue

        start = random.uniform(0, latest_start)
        end = start + clip_duration

        overlaps = any(not (end <= s or start >= s + d) for s, d in clips)
        if overlaps:
            continue

        clips.append((start, clip_duration))

    clips.sort(key=lambda c: c[0])
    return clips