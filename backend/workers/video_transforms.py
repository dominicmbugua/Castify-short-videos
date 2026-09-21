from pathlib import Path
import ffmpeg

TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920


def apply_center_crop(input_path: Path, output_path: Path) -> None:
    """Fills the 9:16 frame, trimming the excess left/right (or top/bottom)."""
    (
        ffmpeg
        .input(str(input_path))
        .filter("scale", TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio="increase")
        .filter("crop", TARGET_WIDTH, TARGET_HEIGHT)
        .output(str(output_path), **{"c:a": "copy"})
        .overwrite_output()
        .run(quiet=True)
    )


def apply_pad_canvas(input_path: Path, output_path: Path) -> None:
    """Keeps the full frame, using a blurred, scaled-up copy of the same
    video as the background instead of plain black bars."""
    src = ffmpeg.input(str(input_path))

    background = (
        src.video
        .filter("scale", TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio="increase")
        .filter("crop", TARGET_WIDTH, TARGET_HEIGHT)
        .filter("boxblur", 20, 1)
    )
    foreground = src.video.filter(
        "scale", TARGET_WIDTH, TARGET_HEIGHT, force_original_aspect_ratio="decrease"
    )
    composed = ffmpeg.filter([background, foreground], "overlay", "(W-w)/2", "(H-h)/2")

    (
        ffmpeg
        .output(composed, src.audio, str(output_path), **{"c:a": "copy"})
        .overwrite_output()
        .run(quiet=True)
    )


def apply_vertical_format(input_path: Path, output_path: Path, vertical_format: str) -> None:
    if vertical_format == "center_crop":
        apply_center_crop(input_path, output_path)
    elif vertical_format == "pad_canvas":
        apply_pad_canvas(input_path, output_path)
    else:
        raise ValueError(f"Unknown vertical_format: {vertical_format}")