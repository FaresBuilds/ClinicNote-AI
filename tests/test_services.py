import json

import pytest
import requests

from services import (
    ServiceError,
    apply_speaker_roles,
    format_transcript,
    generate_reports,
    group_words_into_turns,
    parse_report_response,
    transcribe_audio,
)


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, response=None, error=None, responses=None):
        self.response = response
        self.responses = list(responses or [])
        self.error = error
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        if self.responses:
            return self.responses.pop(0)
        return self.response


def test_group_words_merges_consecutive_speaker_tokens_into_timestamped_turns():
    words = [
        {"text": "Hello", "type": "word", "start": 0.0, "end": 0.4, "speaker_id": "speaker_0"},
        {"text": ",", "type": "word", "start": 0.4, "end": 0.5, "speaker_id": "speaker_0"},
        {"text": "doctor", "type": "word", "start": 0.6, "end": 1.0, "speaker_id": "speaker_0"},
        {"text": "I", "type": "word", "start": 1.2, "end": 1.4, "speaker_id": "speaker_1"},
        {"text": "feel", "type": "word", "start": 1.5, "end": 1.8, "speaker_id": "speaker_1"},
        {"text": "tired", "type": "word", "start": 1.9, "end": 2.3, "speaker_id": "speaker_1"},
    ]

    assert group_words_into_turns(words) == [
        {"speaker_id": "speaker_0", "text": "Hello, doctor", "start": 0.0, "end": 1.0},
        {"speaker_id": "speaker_1", "text": "I feel tired", "start": 1.2, "end": 2.3},
    ]


def test_group_words_keeps_unknown_speaker_and_skips_blank_tokens():
    words = [
        {"text": " ", "type": "spacing", "start": 0.0, "end": 0.1},
        {"text": "(coughs)", "type": "audio_event", "start": 0.1, "end": 0.7},
    ]

    assert group_words_into_turns(words) == [
        {"speaker_id": "speaker_unknown", "text": "(coughs)", "start": 0.1, "end": 0.7}
    ]


def test_apply_roles_is_explicit_and_does_not_guess_unmapped_speakers():
    turns = [
        {"speaker_id": "speaker_0", "text": "How are you?", "start": 0.0, "end": 1.0},
        {"speaker_id": "speaker_1", "text": "Better.", "start": 1.1, "end": 1.8},
        {"speaker_id": "speaker_unknown", "text": "Noise", "start": 2.0, "end": 2.2},
    ]

    labelled = apply_speaker_roles(turns, {"speaker_0": "Doctor", "speaker_1": "Patient"})

    assert [turn["role"] for turn in labelled] == ["Doctor", "Patient", "Unknown speaker"]
    assert "role" not in turns[0]


def test_format_transcript_includes_roles_and_readable_timestamps():
    turns = [
        {"speaker_id": "speaker_0", "role": "Doctor", "text": "Tell me more.", "start": 65.2, "end": 68.9}
    ]

    assert format_transcript(turns) == "[01:05 - 01:08] Doctor: Tell me more."


@pytest.mark.parametrize("fenced", [False, True])
def test_parse_report_response_accepts_plain_or_fenced_json(fenced):
    report = {
        "doctor_report": {
            "patient_complaints": ["Headache"],
            "symptoms_mentioned": ["Pain"],
            "relevant_history": ["Not mentioned in the conversation"],
            "clinical_considerations": ["Cause was not established"],
            "medications_mentioned": ["Paracetamol was discussed"],
            "tests_investigations": ["Blood pressure check"],
            "doctor_recommendations": ["Rest"],
            "follow_up_instructions": ["Return if worse"],
            "consultation_summary": "A short consultation summary.",
        },
        "patient_report": {
            "what_was_discussed": "The headache was discussed.",
            "main_symptoms_complaints": ["Headache"],
            "doctor_recommendations": ["Rest"],
            "medicines_mentioned": ["Paracetamol"],
            "tests_requested": ["Blood pressure check"],
            "things_to_remember": ["Seek help if symptoms worsen"],
            "follow_up_instructions": ["Return if worse"],
        },
    }
    content = json.dumps(report)
    if fenced:
        content = f"```json\n{content}\n```"

    assert parse_report_response(content) == report


def test_parse_report_response_rejects_missing_required_sections():
    with pytest.raises(ServiceError, match="missing required sections"):
        parse_report_response('{"doctor_report": {}}')


@pytest.mark.parametrize(
    "report",
    [
        {"doctor_report": {}, "patient_report": {}},
        {
            "doctor_report": {
                "patient_complaints": "Headache",
                "symptoms_mentioned": ["Pain"],
                "relevant_history": ["Not mentioned"],
                "clinical_considerations": ["Uncertain cause"],
                "medications_mentioned": ["None mentioned"],
                "tests_investigations": ["None mentioned"],
                "doctor_recommendations": ["Rest"],
                "follow_up_instructions": ["Return if worse"],
                "consultation_summary": "Headache discussed.",
            },
            "patient_report": {
                "what_was_discussed": "Your headache.",
                "main_symptoms_complaints": ["Headache"],
                "doctor_recommendations": ["Rest"],
                "medicines_mentioned": ["None mentioned"],
                "tests_requested": ["None mentioned"],
                "things_to_remember": ["Watch for worsening symptoms"],
                "follow_up_instructions": ["Return if worse"],
            },
        },
    ],
)
def test_parse_report_response_rejects_incomplete_or_wrongly_typed_fields(report):
    with pytest.raises(ServiceError, match="missing or invalid fields"):
        parse_report_response(json.dumps(report))


def test_transcribe_audio_uses_medical_scribe_diarization_and_returns_turns():
    session = FakeSession(
        FakeResponse(
            {
                "language_code": "ar",
                "language_probability": 0.99,
                "text": "أهلاً كيف حالك",
                "words": [
                    {"text": "أهلاً", "type": "word", "start": 0.0, "end": 0.5, "speaker_id": "speaker_0"},
                    {"text": "كيف", "type": "word", "start": 0.8, "end": 1.0, "speaker_id": "speaker_1"},
                    {"text": "حالك", "type": "word", "start": 1.1, "end": 1.5, "speaker_id": "speaker_1"},
                ],
            }
        )
    )

    result = transcribe_audio(b"wav-data", "visit.wav", "eleven-key", session=session)

    url, request = session.calls[0]
    assert url == "https://api.elevenlabs.io/v1/speech-to-text"
    assert request["headers"] == {"xi-api-key": "eleven-key"}
    assert request["data"]["model_id"] == "scribe_v2_medical"
    assert request["data"]["diarize"] == "true"
    assert request["data"]["num_speakers"] == "2"
    assert request["data"]["timestamps_granularity"] == "word"
    assert result["language_code"] == "ar"
    assert result["speaker_ids"] == ["speaker_0", "speaker_1"]
    assert result["turns"][1]["text"] == "كيف حالك"


def test_transcribe_audio_rejects_empty_transcription():
    session = FakeSession(FakeResponse({"text": "", "words": []}))

    with pytest.raises(ServiceError, match="could not detect any speech"):
        transcribe_audio(b"wav-data", "visit.wav", "eleven-key", session=session)


def test_transcribe_audio_does_not_offer_unknown_audio_events_as_role_choices():
    session = FakeSession(
        FakeResponse(
            {
                "text": "Hello (coughs) I feel tired",
                "words": [
                    {"text": "Hello", "start": 0.0, "end": 0.4, "speaker_id": "speaker_0"},
                    {"text": "(coughs)", "start": 0.5, "end": 0.8, "speaker_id": None},
                    {"text": "I feel tired", "start": 0.9, "end": 1.5, "speaker_id": "speaker_1"},
                ],
            }
        )
    )

    result = transcribe_audio(b"wav-data", "visit.wav", "eleven-key", session=session)

    assert result["speaker_ids"] == ["speaker_0", "speaker_1"]
    assert result["turns"][1]["speaker_id"] == "speaker_unknown"


def test_transcribe_audio_repairs_collapsed_medical_diarization_with_standard_scribe():
    medical_words = [
        {
            "text": f"medical-{index}",
            "type": "word",
            "start": float(index * 4),
            "end": float(index * 4 + 1),
            "speaker_id": "speaker_0" if index == 0 else "speaker_1",
        }
        for index in range(12)
    ]
    diarization_words = [
        {
            "text": f"base-{index}",
            "type": "word",
            "start": float(index * 4),
            "end": float(index * 4 + 1),
            "speaker_id": "speaker_0" if (index // 3) % 2 == 0 else "speaker_1",
        }
        for index in range(12)
    ]
    session = FakeSession(
        responses=[
            FakeResponse({"text": "medical transcript", "words": medical_words}),
            FakeResponse({"text": "base transcript", "words": diarization_words}),
        ]
    )

    result = transcribe_audio(b"mp3-data", "visit.mp3", "eleven-key", session=session)

    assert [call[1]["data"]["model_id"] for call in session.calls] == [
        "scribe_v2_medical",
        "scribe_v2",
    ]
    assert result["text"] == "medical transcript"
    assert result["diarization_fallback_used"] is True
    assert [turn["speaker_id"] for turn in result["turns"]] == [
        "speaker_0",
        "speaker_1",
        "speaker_0",
        "speaker_1",
    ]
    assert result["turns"][0]["text"] == "medical-0 medical-1 medical-2"


def test_transcribe_audio_stops_when_both_diarization_passes_are_collapsed():
    collapsed_words = [
        {
            "text": f"word-{index}",
            "type": "word",
            "start": float(index * 4),
            "end": float(index * 4 + 1),
            "speaker_id": "speaker_0" if index == 0 else "speaker_1",
        }
        for index in range(12)
    ]
    session = FakeSession(
        responses=[
            FakeResponse({"text": "medical transcript", "words": collapsed_words}),
            FakeResponse({"text": "base transcript", "words": collapsed_words}),
        ]
    )

    with pytest.raises(ServiceError, match="could not separate the two speakers reliably"):
        transcribe_audio(b"mp3-data", "visit.mp3", "eleven-key", session=session)


def test_transcribe_audio_hides_network_error_details():
    session = FakeSession(error=requests.RequestException("request included secret-key"))

    with pytest.raises(ServiceError, match="ElevenLabs could not transcribe") as exc:
        transcribe_audio(b"wav-data", "visit.wav", "secret-key", session=session)

    assert "secret-key" not in str(exc.value)


def test_generate_reports_sends_structured_gemini_request_and_parses_result():
    report = {
        "doctor_report": {
            "patient_complaints": ["Headache"],
            "symptoms_mentioned": ["Pain"],
            "relevant_history": ["Not mentioned"],
            "clinical_considerations": ["Uncertain cause"],
            "medications_mentioned": ["None mentioned"],
            "tests_investigations": ["None mentioned"],
            "doctor_recommendations": ["Rest"],
            "follow_up_instructions": ["Return if worse"],
            "consultation_summary": "Headache discussed.",
        },
        "patient_report": {
            "what_was_discussed": "Your headache.",
            "main_symptoms_complaints": ["Headache"],
            "doctor_recommendations": ["Rest"],
            "medicines_mentioned": ["None mentioned"],
            "tests_requested": ["None mentioned"],
            "things_to_remember": ["Watch for worsening symptoms"],
            "follow_up_instructions": ["Return if worse"],
        },
    }
    session = FakeSession(FakeResponse({"choices": [{"message": {"content": json.dumps(report)}}]}))

    result = generate_reports(
        "[00:00 - 00:01] Doctor: Hello",
        "openrouter-key",
        model="google/gemini-test",
        session=session,
    )

    url, request = session.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert request["headers"]["Authorization"] == "Bearer openrouter-key"
    assert request["json"]["model"] == "google/gemini-test"
    assert request["json"]["response_format"]["type"] == "json_schema"
    assert request["json"]["provider"] == {"require_parameters": True}
    assert result == report


def test_generate_reports_rejects_empty_transcript_without_network_call():
    session = FakeSession()

    with pytest.raises(ServiceError, match="Transcript is empty"):
        generate_reports("  ", "openrouter-key", session=session)

    assert session.calls == []


def test_generate_reports_hides_openrouter_failure_details():
    session = FakeSession(error=requests.Timeout("Bearer private-key"))

    with pytest.raises(ServiceError, match="OpenRouter could not generate") as exc:
        generate_reports("Doctor: Hello", "private-key", session=session)

    assert "private-key" not in str(exc.value)
