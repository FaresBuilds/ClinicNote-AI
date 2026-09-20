# Medical Consultation Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the complete local Streamlit doctor-patient transcription and reporting demo.

**Architecture:** Keep UI/orchestration in `app.py`, external API and transcript/report transformation in `services.py`, and local persistence in `storage.py`. Use direct HTTP calls to minimize dependencies and keep API contracts visible.

**Tech Stack:** Python 3.10+, Streamlit, Requests, python-dotenv, pytest

**Spec:** `docs/superpowers/specs/2026-09-20-medical-consultation-demo-design.md`

## Global Constraints

- Use `scribe_v2_medical`, speaker diarization, exactly two expected speakers, and word timestamps.
- Never infer doctor/patient roles; the user maps the speakers.
- Keep keys server-side and load them only from environment variables.
- Store all artifacts locally; do not add a database or server framework.
- Prefer clear, minimal code and friendly user-facing failures.

## Review Focus

- ElevenLabs words with punctuation/audio events or a missing speaker ID still produce readable turns.
- A one-speaker recording does not break role selectors or transcript rendering.
- OpenRouter content wrapped in Markdown fences still parses safely.
- Duplicate filenames cannot overwrite an earlier consultation.
- An API failure never exposes keys or a Python traceback in the UI.

---

### Task 1: Pure transformations and local storage

**Files:**
- Create: `services.py`
- Create: `storage.py`
- Create: `tests/test_services.py`
- Create: `tests/test_storage.py`

**Interfaces:**
- Produces: `group_words_into_turns(words)`, `apply_speaker_roles(turns, mapping)`, `format_transcript(turns)`, `parse_report_response(content)`, `validate_audio(name, data)`, and `save_bytes/save_text`.

- [ ] Write tests using literal ElevenLabs-shaped word fixtures, fenced and plain JSON responses, valid audio bytes, empty input, invalid extensions, and duplicate saves.
- [ ] Run `pytest -q` and confirm imports or missing functions fail.
- [ ] Implement the smallest pure transformation and storage functions that satisfy the cases.
- [ ] Run `pytest -q` and confirm all Task 1 tests pass.

### Task 2: External API clients

**Files:**
- Modify: `services.py`
- Modify: `tests/test_services.py`

**Interfaces:**
- Consumes: grouped/role-labelled turns from Task 1.
- Produces: `transcribe_audio(...)` and `generate_reports(...)` with timeouts, status validation, and sanitized `ServiceError` messages.

- [ ] Add boundary tests with complete HTTP response doubles that assert returned application data and failure behavior.
- [ ] Run `pytest -q` and confirm the missing client behavior fails.
- [ ] Implement direct ElevenLabs multipart and OpenRouter JSON requests, strict schema output, and response validation.
- [ ] Run `pytest -q` and confirm the complete suite passes.

### Task 3: Streamlit experience and runnable project

**Files:**
- Create: `app.py`
- Create: `requirements.txt`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `README.md`
- Create: `.streamlit/config.toml`

**Interfaces:**
- Consumes: all public functions from `services.py` and `storage.py`.
- Produces: one-page upload/record/process/map/report workflow and local run instructions.

- [ ] Implement the polished page, session-state workflow, progress stages, speaker selectors, transcript bubbles, report cards, friendly errors, and downloads.
- [ ] Install requirements and run `pytest -q`.
- [ ] Compile all Python files and start Streamlit headlessly; confirm the health endpoint responds.
- [ ] Make authenticated smoke calls to verify ElevenLabs accepts the configured medical transcription request and OpenRouter returns parseable Gemini structured output.

