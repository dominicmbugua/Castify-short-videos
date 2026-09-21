import hashlib
from pathlib import Path
import ffmpeg

from workers.video_transforms import TARGET_WIDTH, TARGET_HEIGHT


def extract_and_format_clip(
    source_path: Path,
    output_path: Path,
    start_sec: float,
    duration_sec: float,
    vertical_format: str,
) -> None:
    """
    Cuts the planned segment from the source and applies the chosen
    vertical-format transform in a single ffmpeg pass.
    """
    src = ffmpeg.input(str(source_path), ss=start_sec, t=duration_sec)

    if vertical_format == "center_crop":
        video = (
            src.video
            .filter("scale", TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio="increase")
            .filter("crop", TARGET_WIDTH, TARGET_HEIGHT)
        )
    elif vertical_format == "pad_canvas":
        background = (
            src.video
            .filter("scale", TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio="increase")
            .filter("crop", TARGET_WIDTH, TARGET_HEIGHT)
            .filter("boxblur", 20, 1)
        )
        foreground = src.video.filter(
            "scale", TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio="decrease"
        )
        video = ffmpeg.filter([background, foreground], "overlay", "(W-w)/2", "(H-h)/2")
    else:
        raise ValueError(f"Unknown vertical_format: {vertical_format}")

    try:
        (
            ffmpeg
            .output(
                video, src.audio, str(output_path),
                vcodec="libx264", acodec="aac", **{"movflags": "+faststart"},
            )
            .overwrite_output()
            .run(quiet=True, capture_stdout=True, capture_stderr=True)
        )
    except ffmpeg.Error as e:
        stderr = e.stderr.decode(errors="replace") if e.stderr else "(no stderr captured)"
        raise RuntimeError(f"ffmpeg failed: {stderr[-2000:]}") from e


def compute_content_hash(path: Path) -> str:
    """Section 8.3 — checksum of the finished, encoded clip file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()