from pathlib import Path

import pytest

from storage import (
    StorageError,
    microphone_access_message,
    save_bytes,
    save_text,
    validate_audio,
)


def test_validate_audio_accepts_supported_file_and_returns_safe_name():
    assert validate_audio("../My Visit.MP3", b"audio-data") == "My Visit.MP3"


@pytest.mark.parametrize(
    ("name", "data", "message"),
    [
        ("visit.exe", b"audio-data", "Unsupported audio format"),
        ("visit.wav", b"", "empty"),
    ],
)
def test_validate_audio_rejects_invalid_input(name, data, message):
    with pytest.raises(StorageError, match=message):
        validate_audio(name, data)


@pytest.mark.parametrize(
    ("url", "is_embedded", "expected_fragment"),
    [
        ("http://localhost:8501", False, None),
        ("http://127.0.0.1:8501", False, None),
        ("https://example.ngrok-free.app", False, None),
        ("http://192.168.1.35:8501", False, "HTTPS or localhost"),
        ("https://example.com", True, "directly in Chrome or Edge"),
    ],
)
def test_microphone_access_message_flags_browser_contexts_that_block_recording(
    url, is_embedded, expected_fragment
):
    message = microphone_access_message(url, is_embedded)

    if expected_fragment is None:
        assert message is None
    else:
        assert expected_fragment in message


def test_save_bytes_does_not_overwrite_duplicate_names(tmp_path: Path):
    first = save_bytes(tmp_path, b"first", "visit.wav")
    second = save_bytes(tmp_path, b"second", "visit.wav")

    assert first != second
    assert first.read_bytes() == b"first"
    assert second.read_bytes() == b"second"


def test_save_text_creates_directory_and_utf8_file(tmp_path: Path):
    target = save_text(tmp_path / "reports", "ملخص الزيارة", "patient-report")

    assert target.read_text(encoding="utf-8") == "ملخص الزيارة"
    assert target.parent == tmp_path / "reports"
