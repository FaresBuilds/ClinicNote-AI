"""Simple local artifact storage for the Streamlit demo."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga", ".webm", ".ogg"}
MAX_AUDIO_BYTES = 500 * 1024 * 1024


class StorageError(ValueError):
    """A safe, user-facing validation or storage error."""


def microphone_access_message(url: str, is_embedded: bool) -> str | None:
    """Explain browser contexts where microphone capture cannot be used reliably."""
    if is_embedded:
        return (
            "Microphone access is usually blocked inside embedded previews. "
            "Open this app directly in Chrome or Edge, then allow microphone access, "
            "or switch to Upload audio."
        )

    parsed = urlparse(url or "")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        return (
            "Browsers block microphone access on non-secure network addresses. "
            "Open the app with HTTPS or localhost, then allow microphone access, "
            "or switch to Upload audio."
        )
    return None


def validate_audio(name: str, data: bytes) -> str:
    safe_name = Path(name or "recording.wav").name
    if not data:
        raise StorageError("The selected audio file is empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise StorageError("The audio file is larger than the 500 MB demo limit.")
    if Path(safe_name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise StorageError("Unsupported audio format. Use WAV, MP3, M4A, MP4, MPEG, MPGA, WEBM, or OGG.")
    return safe_name


def _unique_name(stem: str, suffix: str) -> str:
    clean_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-") or "consultation"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{clean_stem}-{uuid4().hex[:8]}{suffix}"


def save_bytes(directory: str | Path, data: bytes, original_name: str) -> Path:
    safe_name = validate_audio(original_name, data)
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    source = Path(safe_name)
    target = target_dir / _unique_name(source.stem, source.suffix.lower())
    target.write_bytes(data)
    return target


def save_text(directory: str | Path, text: str, prefix: str) -> Path:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _unique_name(prefix, ".txt")
    target.write_text(text, encoding="utf-8")
    return target
