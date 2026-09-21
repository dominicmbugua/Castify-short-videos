import os
import re
from typing import Optional
from urllib.parse import urlparse, unquote

# Some sources prefix filenames with an upload timestamp, e.g.
# 20201204174233072cup-of-coffee.mp4 (YYYYMMDDHHMMSSmmm = 17 digits).
# Only a long leading run of digits is stripped, so a title like
# "2020-highlights.mp4" or "1917-trailer.mp4" is left alone.
_LEADING_TIMESTAMP = re.compile(r"^\d{14,}[\s._-]*")


def clean_filename_title(name: str) -> str:
    """Drops a leading upload timestamp from a filename, keeping the extension.
    If nothing would be left, the original name is returned unchanged."""
    stem, ext = os.path.splitext(name)
    cleaned = _LEADING_TIMESTAMP.sub("", stem)
    return f"{cleaned}{ext}" if cleaned else name


def filename_from_url(url: str) -> Optional[str]:
    """For a direct file link (…/some-video.mp4) returns the cleaned filename.
    Returns None when the URL path doesn't end in a filename with an extension
    (e.g. a YouTube watch page)."""
    path = urlparse(url).path
    name = unquote(os.path.basename(path.rstrip("/")))
    if name and os.path.splitext(name)[1]:
        return clean_filename_title(name)
    return None


def title_from_url(url: str) -> Optional[str]:
    """Best-effort title for a URL source: the cleaned filename if there is
    one, otherwise the hostname as a placeholder."""
    return filename_from_url(url) or urlparse(url).netloc or None