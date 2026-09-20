"""External service clients and small transcript/report transformations."""

from __future__ import annotations

import json
import mimetypes
import re
from typing import Any

import requests


ELEVENLABS_STT_URL = "https://api.elevenlabs.io/v1/speech-to-text"
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
DEFAULT_OPENROUTER_MODEL = "google/gemini-3.8-flash"


class ServiceError(RuntimeError):
    """A safe, user-facing error from an external service or its response."""


def _read(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _join_token(current: str, token: str) -> str:
    if not current:
        return token.strip()
    if token[:1].isspace() or current[-1:].isspace():
        return current + token
    if token in {".", ",", "!", "?", ":", ";", "%", ")", "]", "}"}:
        return current + token
    return f"{current} {token}"


def group_words_into_turns(words: list[Any]) -> list[dict[str, Any]]:
    """Group adjacent ElevenLabs word entries into speaker turns."""
    turns: list[dict[str, Any]] = []
    active: dict[str, Any] | None = None

    for word in words or []:
        token = str(_read(word, "text", "") or "")
        if not token.strip():
            continue

        speaker_id = str(_read(word, "speaker_id", None) or "speaker_unknown")
        start = _read(word, "start", None)
        end = _read(word, "end", None)

        if active is None or active["speaker_id"] != speaker_id:
            if active and active["text"].strip():
                active["text"] = active["text"].strip()
                turns.append(active)
            active = {
                "speaker_id": speaker_id,
                "text": token.strip(),
                "start": start,
                "end": end,
            }
        else:
            active["text"] = _join_token(active["text"], token)
            if end is not None:
                active["end"] = end

    if active and active["text"].strip():
        active["text"] = active["text"].strip()
        turns.append(active)

    return turns


def _diarization_is_suspicious(words: list[Any], turns: list[dict[str, Any]]) -> bool:
    """Detect a long two-person recording collapsed almost entirely to one speaker."""
    spoken_words = [
        word
        for word in words or []
        if str(_read(word, "text", "") or "").strip()
        and _read(word, "speaker_id", None)
        and _read(word, "start", None) is not None
        and _read(word, "end", None) is not None
    ]
    if len(spoken_words) < 10:
        return False

    starts = [float(_read(word, "start")) for word in spoken_words]
    ends = [float(_read(word, "end")) for word in spoken_words]
    if max(ends) - min(starts) < 30:
        return False

    speaker_counts: dict[str, int] = {}
    for word in spoken_words:
        speaker_id = str(_read(word, "speaker_id"))
        speaker_counts[speaker_id] = speaker_counts.get(speaker_id, 0) + 1

    if len(speaker_counts) < 2:
        return True
    dominant_ratio = max(speaker_counts.values()) / len(spoken_words)
    return dominant_ratio >= 0.9 and len(turns) <= 3


def _transfer_speaker_labels(medical_words: list[Any], diarization_words: list[Any]) -> list[dict[str, Any]]:
    """Apply timestamp-aligned speaker labels while preserving the medical transcript tokens."""
    timeline = []
    for word in diarization_words or []:
        start = _read(word, "start", None)
        end = _read(word, "end", None)
        speaker_id = _read(word, "speaker_id", None)
        if start is None or end is None or not speaker_id:
            continue
        timeline.append((float(start), float(end), str(speaker_id)))
    timeline.sort(key=lambda item: item[0])

    if not timeline:
        return [dict(word) for word in medical_words]

    repaired: list[dict[str, Any]] = []
    timeline_index = 0
    last_speaker = timeline[0][2]
    for word in medical_words or []:
        copied = dict(word)
        start = _read(word, "start", None)
        end = _read(word, "end", None)
        if start is not None and end is not None:
            midpoint = (float(start) + float(end)) / 2
            while (
                timeline_index + 1 < len(timeline)
                and (timeline[timeline_index + 1][0] + timeline[timeline_index + 1][1]) / 2
                <= midpoint
            ):
                timeline_index += 1
            current = timeline[timeline_index]
            if timeline_index + 1 < len(timeline):
                following = timeline[timeline_index + 1]
                current_distance = abs(((current[0] + current[1]) / 2) - midpoint)
                following_distance = abs(((following[0] + following[1]) / 2) - midpoint)
                if following_distance < current_distance:
                    current = following
            last_speaker = current[2]
        copied["speaker_id"] = last_speaker
        repaired.append(copied)
    return repaired


def _request_elevenlabs_transcription(
    audio_bytes: bytes,
    filename: str,
    mime_type: str,
    api_key: str,
    model_id: str,
    session: Any,
    timeout: int,
) -> dict[str, Any]:
    try:
        response = session.post(
            ELEVENLABS_STT_URL,
            headers={"xi-api-key": api_key},
            files={"file": (filename, audio_bytes, mime_type)},
            data={
                "model_id": model_id,
                "diarize": "true",
                "num_speakers": "2",
                "timestamps_granularity": "word",
                "tag_audio_events": "true",
            },
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ServiceError(
            "ElevenLabs could not transcribe this recording. Check the file, API key, and connection, then try again."
        ) from exc

    try:
        return response.json()
    except (ValueError, TypeError) as exc:
        raise ServiceError("ElevenLabs returned an unreadable transcription. Please try again.") from exc


def _speaker_label(speaker_id: str) -> str:
    match = re.search(r"(\d+)$", speaker_id)
    if match:
        return f"Speaker {int(match.group(1)) + 1}"
    return "Unknown speaker"


def apply_speaker_roles(
    turns: list[dict[str, Any]], mapping: dict[str, str]
) -> list[dict[str, Any]]:
    """Return copied turns labelled only by the explicit user mapping."""
    return [
        {**turn, "role": mapping.get(turn["speaker_id"], _speaker_label(turn["speaker_id"]))}
        for turn in turns
    ]


def format_timestamp(seconds: float | int | None) -> str:
    total = max(0, int(seconds or 0))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def format_transcript(turns: list[dict[str, Any]]) -> str:
    lines = []
    for turn in turns:
        start = format_timestamp(turn.get("start"))
        end = format_timestamp(turn.get("end"))
        role = turn.get("role") or _speaker_label(turn.get("speaker_id", ""))
        lines.append(f"[{start} - {end}] {role}: {turn.get('text', '').strip()}")
    return "\n\n".join(lines)


def parse_report_response(content: str) -> dict[str, Any]:
    """Parse and minimally validate an OpenRouter structured response."""
    cleaned = (content or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        report = json.loads(cleaned)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ServiceError("The report service returned an unreadable response. Please try again.") from exc

    if not isinstance(report, dict) or not all(
        isinstance(report.get(key), dict) for key in ("doctor_report", "patient_report")
    ):
        raise ServiceError("The generated report is missing required sections. Please try again.")
    _validate_report_fields(report)
    return report


def transcribe_audio(
    audio_bytes: bytes,
    filename: str,
    api_key: str,
    *,
    session: Any = requests,
    timeout: int = 300,
) -> dict[str, Any]:
    """Transcribe clinical audio with ElevenLabs Scribe v2 Medical."""
    mime_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    payload = _request_elevenlabs_transcription(
        audio_bytes, filename, mime_type, api_key, "scribe_v2_medical", session, timeout
    )

    words = payload.get("words") or []
    turns = group_words_into_turns(words)
    diarization_fallback_used = False
    if _diarization_is_suspicious(words, turns):
        diarization_payload = _request_elevenlabs_transcription(
            audio_bytes, filename, mime_type, api_key, "scribe_v2", session, timeout
        )
        diarization_words = diarization_payload.get("words") or []
        diarization_turns = group_words_into_turns(diarization_words)
        diarization_speakers = {
            str(_read(word, "speaker_id"))
            for word in diarization_words
            if _read(word, "speaker_id", None)
        }
        if len(diarization_speakers) < 2 or _diarization_is_suspicious(
            diarization_words, diarization_turns
        ):
            raise ServiceError(
                "ElevenLabs could not separate the two speakers reliably. Try a clearer recording with less overlap."
            )
        repaired_words = _transfer_speaker_labels(words, diarization_words)
        repaired_turns = group_words_into_turns(repaired_words)
        if repaired_turns:
            words = repaired_words
            turns = repaired_turns
            diarization_fallback_used = True

    full_text = str(payload.get("text") or "").strip()
    if not turns and full_text:
        turns = [{"speaker_id": "speaker_unknown", "text": full_text, "start": 0.0, "end": None}]
    if not turns:
        raise ServiceError("ElevenLabs could not detect any speech in this recording.")

    all_speaker_ids = list(dict.fromkeys(turn["speaker_id"] for turn in turns))
    identified_speakers = [speaker_id for speaker_id in all_speaker_ids if speaker_id != "speaker_unknown"]
    speaker_ids = identified_speakers or all_speaker_ids
    return {
        "text": full_text or " ".join(turn["text"] for turn in turns),
        "language_code": payload.get("language_code"),
        "language_probability": payload.get("language_probability"),
        "turns": turns,
        "speaker_ids": speaker_ids,
        "diarization_fallback_used": diarization_fallback_used,
    }


def _string_array(description: str) -> dict[str, Any]:
    return {"type": "array", "description": description, "items": {"type": "string"}}


DOCTOR_PROPERTIES = {
    "patient_complaints": _string_array("Complaints explicitly stated by the patient."),
    "symptoms_mentioned": _string_array("Symptoms explicitly mentioned in the transcript."),
    "relevant_history": _string_array("Relevant history stated in the conversation."),
    "clinical_considerations": _string_array("Clearly qualified clinical considerations, not diagnoses."),
    "medications_mentioned": _string_array("Medicines mentioned and only the context explicitly stated."),
    "tests_investigations": _string_array("Tests or investigations mentioned or requested."),
    "doctor_recommendations": _string_array("Recommendations explicitly made by the doctor."),
    "follow_up_instructions": _string_array("Follow-up instructions explicitly stated."),
    "consultation_summary": {"type": "string", "description": "A concise, factual consultation summary."},
}

PATIENT_PROPERTIES = {
    "what_was_discussed": {"type": "string", "description": "A simple-language overview."},
    "main_symptoms_complaints": _string_array("Symptoms and complaints in simple language."),
    "doctor_recommendations": _string_array("The doctor's stated recommendations in simple language."),
    "medicines_mentioned": _string_array("Medicines mentioned, without inventing instructions."),
    "tests_requested": _string_array("Tests requested or discussed."),
    "things_to_remember": _string_array("Important points explicitly supported by the transcript."),
    "follow_up_instructions": _string_array("Follow-up instructions in simple language."),
}

REPORT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "doctor_report": {
            "type": "object",
            "additionalProperties": False,
            "properties": DOCTOR_PROPERTIES,
            "required": list(DOCTOR_PROPERTIES),
        },
        "patient_report": {
            "type": "object",
            "additionalProperties": False,
            "properties": PATIENT_PROPERTIES,
            "required": list(PATIENT_PROPERTIES),
        },
    },
    "required": ["doctor_report", "patient_report"],
}


def _validate_report_fields(report: dict[str, Any]) -> None:
    for section_name, section_schema in REPORT_SCHEMA["properties"].items():
        section = report[section_name]
        for field_name, field_schema in section_schema["properties"].items():
            value = section.get(field_name)
            if field_schema["type"] == "string":
                valid = isinstance(value, str) and bool(value.strip())
            else:
                valid = (
                    isinstance(value, list)
                    and bool(value)
                    and all(isinstance(item, str) and bool(item.strip()) for item in value)
                )
            if not valid:
                raise ServiceError(
                    "The generated report has missing or invalid fields. Please try again."
                )


REPORT_SYSTEM_PROMPT = """You create faithful reports from a doctor-patient transcript.
Use only information present in the transcript. Never invent a diagnosis, symptom, medication,
dose, test result, medical history, recommendation, or follow-up instruction. Clearly label any
uncertainty and distinguish stated facts from possible considerations. A clinician's question is
only a topic discussed; it is not evidence that a symptom is present or absent. A negative answer
applies only to the exact symptom or fact the patient explicitly denied. Preserve qualifiers such
as 'I think', 'maybe', 'possible', and 'mild' instead of turning uncertainty into fact. When a
section has no supporting information, write 'Not mentioned in the conversation' rather than
filling the gap. Before returning JSON, check that every claim is supported by the transcript.
Use the transcript's main language. Keep the doctor report clinical and concise. Keep the patient
report simple, calm, and easy to understand. This is a documentation summary, not new medical advice."""


def generate_reports(
    transcript: str,
    api_key: str,
    *,
    model: str = DEFAULT_OPENROUTER_MODEL,
    session: Any = requests,
    timeout: int = 180,
) -> dict[str, Any]:
    """Generate structured doctor and patient reports with Gemini on OpenRouter."""
    if not transcript or not transcript.strip():
        raise ServiceError("Transcript is empty, so reports cannot be generated.")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": REPORT_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Create both reports from this role-labelled transcript:\n\n{transcript}",
            },
        ],
        "temperature": 0.1,
        "max_tokens": 5000,
        "provider": {"require_parameters": True},
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "medical_consultation_reports",
                "strict": True,
                "schema": REPORT_SCHEMA,
            },
        },
    }
    try:
        response = session.post(
            OPENROUTER_CHAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:8501",
                "X-Title": "Clinical Conversation Companion",
            },
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ServiceError(
            "OpenRouter could not generate the reports. Check the API key and connection, then try again."
        ) from exc

    try:
        content = response.json()["choices"][0]["message"]["content"]
    except (ValueError, TypeError, KeyError, IndexError) as exc:
        raise ServiceError("OpenRouter returned an unreadable report response. Please try again.") from exc

    if not isinstance(content, str) or not content.strip():
        raise ServiceError("OpenRouter did not return report content. Please try again.")
    return parse_report_response(content)
