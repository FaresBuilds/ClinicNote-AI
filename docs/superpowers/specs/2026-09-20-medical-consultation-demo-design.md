# Medical Consultation Demo Design

## Goal

Build a small local Streamlit graduation-demo application that turns a recorded or uploaded doctor-patient conversation into a diarized transcript, a clinician-facing report, and a plain-language patient report.

## Architecture

The application has three Python files:

- `app.py` owns the Streamlit page, session state, progress display, manual Doctor/Patient speaker mapping, result tabs, and downloads.
- `services.py` calls ElevenLabs and OpenRouter and converts their responses into small dictionaries used by the UI.
- `storage.py` validates filenames and saves timestamped audio, transcript, and report files under `data/`.

The application loads `ELEVENLABS_API_KEY` and `OPENROUTER_API_KEY` from `.env` or the process environment. `OPENROUTER_MODEL` is optional and defaults to `google/gemini-3.8-flash`.

## Data Flow

1. The user uploads WAV, MP3, M4A, MP4, MPEG, MPGA, WEBM, or OGG audio, or records WAV audio through `st.audio_input`.
2. The selected bytes are validated and saved under `data/audio/`.
3. ElevenLabs receives a multipart request using `model_id=scribe_v2_medical`, `diarize=true`, `num_speakers=2`, and `timestamps_granularity=word`.
4. Consecutive words with the same `speaker_id` are grouped into timestamped conversation turns. Unknown or absent speaker IDs remain neutral labels.
5. The UI presents two selectors. The user explicitly maps Speaker 1 and Speaker 2 to Doctor and Patient; the application never guesses roles.
6. OpenRouter receives the role-labelled transcript and a strict JSON schema. It returns the requested doctor and patient report sections. Empty or unstated sections use explicit wording such as `Not mentioned in the conversation`.
7. Results are saved locally and displayed in Transcript, Doctor Report, and Patient Report tabs with TXT downloads.

## Interface

The page uses a calm navy, teal, and white medical palette; a compact header; a two-option input card; an audio preview; a single primary processing button; progress stages; speaker mapping controls; chat-style transcript bubbles; and report section cards. It includes a visible educational-demo disclaimer and avoids raw API payloads or stack traces.

## Error Handling

Missing keys, empty or unsupported uploads, empty transcription, HTTP failures, timeouts, malformed JSON, and filesystem failures raise concise application errors. The UI catches these and shows a friendly message while retaining the selected audio for retry.

## Verification

Focused tests cover file validation/storage, word-to-turn grouping and role mapping, transcript formatting, and OpenRouter structured-response parsing. Integration smoke checks use the configured keys with tiny requests. Streamlit is launched headlessly and its health endpoint is checked.

