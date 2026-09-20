"""Clinical Conversation Companion — a small Streamlit graduation demo."""

from __future__ import annotations

import html
import os
import sqlite3
from pathlib import Path
from typing import Any

import streamlit as st
from dotenv import load_dotenv

from accounts import (
    AccountError,
    authenticate_user,
    initialize_database,
    register_user,
)
from services import (
    DEFAULT_OPENROUTER_MODEL,
    ServiceError,
    apply_speaker_roles,
    format_timestamp,
    format_transcript,
    generate_reports,
    transcribe_audio,
)
from storage import (
    StorageError,
    build_role_report_pdf,
    microphone_access_message,
    save_bytes,
    save_pdf,
    save_text,
    validate_audio,
)


load_dotenv()

APP_NAME = "Clinical Conversation Companion"
DATA_ROOT = Path("data")
AUDIO_DIR = DATA_ROOT / "audio"
TRANSCRIPT_DIR = DATA_ROOT / "transcripts"
REPORT_DIR = DATA_ROOT / "reports"

DOCTOR_SECTIONS = [
    ("patient_complaints", "Patient complaints", "✦"),
    ("symptoms_mentioned", "Symptoms mentioned", "◉"),
    ("relevant_history", "Relevant history", "◷"),
    ("clinical_considerations", "Clinical considerations", "◇"),
    ("medications_mentioned", "Medications mentioned", "✚"),
    ("tests_investigations", "Tests & investigations", "⌁"),
    ("doctor_recommendations", "Recommendations", "✓"),
    ("follow_up_instructions", "Follow-up", "↗"),
    ("consultation_summary", "Consultation summary", "≡"),
]

PATIENT_SECTIONS = [
    ("what_was_discussed", "What we discussed", "✦"),
    ("main_symptoms_complaints", "Your main symptoms", "◉"),
    ("doctor_recommendations", "What the doctor recommended", "✓"),
    ("medicines_mentioned", "Medicines mentioned", "✚"),
    ("tests_requested", "Tests requested", "⌁"),
    ("things_to_remember", "Things to remember", "★"),
    ("follow_up_instructions", "Your follow-up", "↗"),
]

ARABIC_SECTION_LABELS = {
    "patient_complaints": "شكاوى المريض",
    "symptoms_mentioned": "الأعراض المذكورة",
    "relevant_history": "التاريخ المرضي ذي الصلة",
    "clinical_considerations": "الاعتبارات السريرية",
    "medications_mentioned": "الأدوية المذكورة",
    "tests_investigations": "الفحوصات والتحاليل",
    "doctor_recommendations": "توصيات الطبيب",
    "follow_up_instructions": "تعليمات المتابعة",
    "consultation_summary": "ملخص الاستشارة",
    "what_was_discussed": "ما تمت مناقشته",
    "main_symptoms_complaints": "الأعراض والشكاوى الرئيسية",
    "medicines_mentioned": "الأدوية المذكورة",
    "tests_requested": "الفحوصات المطلوبة",
    "things_to_remember": "أمور يجب تذكرها",
}


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --navy: #102a43;
            --blue: #2563eb;
            --teal: #0f766e;
            --teal-soft: #e9f7f5;
            --ink: #243b53;
            --muted: #627d98;
            --line: #dfe7ef;
            --surface: rgba(255, 255, 255, 0.94);
        }
        .stApp {
            background:
                radial-gradient(circle at 8% 0%, rgba(15,118,110,.10), transparent 28rem),
                radial-gradient(circle at 96% 8%, rgba(37,99,235,.08), transparent 25rem),
                #f6f9fc;
            color: var(--ink);
        }
        [data-testid="stHeader"] { background: rgba(246,249,252,.76); backdrop-filter: blur(12px); }
        [data-testid="stSidebar"] { background: #f0f6f8; }
        .block-container { max-width: 1160px; padding-top: 2.1rem; padding-bottom: 5rem; }
        h1, h2, h3 { color: var(--navy); letter-spacing: -0.025em; }
        .hero {
            position: relative; overflow: hidden;
            background: linear-gradient(130deg, #0b3045 0%, #0d4c5d 54%, #0f766e 100%);
            border-radius: 26px; padding: 2.2rem 2.4rem; color: white;
            box-shadow: 0 24px 60px rgba(16,42,67,.18); margin-bottom: 1.25rem;
        }
        .hero:after {
            content: ""; position: absolute; width: 280px; height: 280px; right: -80px; top: -130px;
            border-radius: 50%; border: 45px solid rgba(255,255,255,.08);
        }
        .hero-kicker { font-size: .76rem; font-weight: 800; letter-spacing: .14em; text-transform: uppercase; color: #a7f3d0; }
        .hero h1 { color: white; margin: .35rem 0 .5rem; font-size: clamp(2rem, 5vw, 3rem); line-height: 1.05; }
        .hero p { color: #d7eef0; margin: 0; max-width: 710px; font-size: 1.03rem; }
        .section-label { color: var(--teal); font-weight: 800; font-size: .78rem; letter-spacing: .12em; text-transform: uppercase; margin-top: .4rem; }
        div[data-testid="stVerticalBlockBorderWrapper"] {
            background: var(--surface); border-color: var(--line) !important; border-radius: 20px;
            box-shadow: 0 10px 32px rgba(16,42,67,.06);
        }
        [data-testid="stFileUploaderDropzone"] {
            background: linear-gradient(135deg, #f8fffe, #f4f8ff); border: 1.5px dashed #8cc7c1;
            border-radius: 16px; padding: 1.15rem;
        }
        .stButton > button[kind="primary"], .stDownloadButton > button {
            border-radius: 12px; min-height: 2.85rem; font-weight: 750;
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #0f766e, #0b5f73); border: 0;
            box-shadow: 0 9px 22px rgba(15,118,110,.22);
        }
        [data-testid="stStatusWidget"] { border-radius: 16px; border-color: #badfd9; background: #f7fffd; }
        .step-row { display: flex; align-items: center; gap: .7rem; margin: .3rem 0 1rem; color: var(--muted); font-size: .9rem; }
        .step { display: inline-flex; align-items: center; gap: .38rem; }
        .step-num { width: 1.55rem; height: 1.55rem; display: inline-grid; place-items: center; border-radius: 50%; background: #e5edf4; color: #486581; font-size: .72rem; font-weight: 800; }
        .step.active .step-num { background: var(--teal); color: white; }
        .step-line { height: 1px; width: 30px; background: #d4dee8; }
        [data-baseweb="tab-list"] { gap: .45rem; background: #eaf0f5; padding: .35rem; border-radius: 14px; }
        [data-baseweb="tab"] { border-radius: 10px; padding: .65rem 1rem; font-weight: 700; }
        [aria-selected="true"][data-baseweb="tab"] { background: white; box-shadow: 0 3px 12px rgba(16,42,67,.08); }
        .transcript-wrap { padding: .5rem 0; }
        .bubble-row { display: flex; margin: .8rem 0; }
        .bubble-row.patient { justify-content: flex-end; }
        .bubble { max-width: 76%; border: 1px solid var(--line); border-radius: 17px 17px 17px 5px; padding: .85rem 1rem; background: white; box-shadow: 0 6px 18px rgba(16,42,67,.055); }
        .bubble-row.patient .bubble { background: linear-gradient(135deg, #eaf8f6, #e9f4fb); border-color: #c9e4e1; border-radius: 17px 17px 5px 17px; }
        .bubble-head { display: flex; justify-content: space-between; gap: 1rem; margin-bottom: .38rem; }
        .speaker { color: var(--teal); font-weight: 800; font-size: .82rem; }
        .time { color: #829ab1; font-size: .73rem; white-space: nowrap; }
        .bubble-text { color: var(--ink); line-height: 1.58; }
        .report-card { background: white; border: 1px solid var(--line); border-radius: 16px; padding: 1rem 1.05rem; margin: .75rem 0; box-shadow: 0 5px 18px rgba(16,42,67,.045); }
        .report-card.patient { border-left: 4px solid #0f766e; }
        .report-card.doctor { border-left: 4px solid #2563eb; }
        .report-title { font-weight: 820; color: var(--navy); margin-bottom: .45rem; }
        .report-icon { display: inline-grid; place-items: center; width: 1.7rem; height: 1.7rem; margin-right: .45rem; border-radius: 8px; background: #edf5f8; color: var(--teal); }
        .report-body { color: #486581; line-height: 1.6; }
        .report-body ul { margin: .25rem 0 0; padding-left: 1.25rem; }
        .report-body li { margin: .28rem 0; }
        .meta-row { display: flex; gap: .5rem; flex-wrap: wrap; margin: .25rem 0 1rem; }
        .meta-pill { font-size: .75rem; color: #486581; background: #edf3f7; border-radius: 999px; padding: .35rem .65rem; }
        @media (max-width: 700px) {
            .block-container { padding: 1rem .85rem 3rem; }
            .hero { padding: 1.6rem 1.25rem; border-radius: 20px; }
            .bubble { max-width: 91%; }
            .step-line { width: 12px; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def initialize_state() -> None:
    defaults = {
        "transcription": None,
        "reports": None,
        "report_mapping": None,
        "audio_path": None,
        "doctor_pdf_report": None,
        "doctor_pdf_path": None,
        "patient_pdf_report": None,
        "patient_pdf_path": None,
        "current_user": None,
        "delivery_token": None,
        "sent_consultation_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def require_keys() -> tuple[str, str, str]:
    elevenlabs_key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    model = os.getenv("OPENROUTER_MODEL", DEFAULT_OPENROUTER_MODEL).strip() or DEFAULT_OPENROUTER_MODEL
    if not elevenlabs_key or not openrouter_key:
        missing = []
        if not elevenlabs_key:
            missing.append("ELEVENLABS_API_KEY")
        if not openrouter_key:
            missing.append("OPENROUTER_API_KEY")
        raise StorageError(f"Missing environment variable: {', '.join(missing)}")
    return elevenlabs_key, openrouter_key, model


def selected_audio(mode: str, uploaded: Any, recorded: Any) -> tuple[str, bytes] | None:
    source = uploaded if mode == "Upload audio" else recorded
    if source is None:
        return None
    name = getattr(source, "name", "recording.wav") or "recording.wav"
    data = source.getvalue()
    return validate_audio(name, data), data


def speaker_title(speaker_id: str, speaker_ids: list[str]) -> str:
    try:
        return f"Speaker {speaker_ids.index(speaker_id) + 1}"
    except ValueError:
        return "Unknown speaker"


def neutral_transcript(turns: list[dict[str, Any]], speaker_ids: list[str]) -> str:
    mapping = {speaker_id: speaker_title(speaker_id, speaker_ids) for speaker_id in speaker_ids}
    return format_transcript(apply_speaker_roles(turns, mapping))


def render_steps(active: int) -> None:
    labels = ["Add audio", "Review speakers", "Read reports"]
    pieces = []
    for index, label in enumerate(labels, start=1):
        state = " active" if index <= active else ""
        pieces.append(f'<span class="step{state}"><span class="step-num">{index}</span>{label}</span>')
        if index < len(labels):
            pieces.append('<span class="step-line"></span>')
    st.markdown(f'<div class="step-row">{"".join(pieces)}</div>', unsafe_allow_html=True)


def render_transcript(turns: list[dict[str, Any]]) -> None:
    st.markdown('<div class="transcript-wrap">', unsafe_allow_html=True)
    for turn in turns:
        role = str(turn.get("role") or "Speaker")
        display_role = str(turn.get("display_role") or role)
        css_role = "patient" if role == "Patient" else "doctor"
        timestamp = f"{format_timestamp(turn.get('start'))} – {format_timestamp(turn.get('end'))}"
        st.markdown(
            f"""
            <div class="bubble-row {css_role}">
              <div class="bubble">
                <div class="bubble-head">
                  <span class="speaker">{html.escape(display_role)}</span>
                  <span class="time">{html.escape(timestamp)}</span>
                </div>
                <div class="bubble-text" dir="auto">{html.escape(str(turn.get('text', '')))}</div>
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )
    st.markdown("</div>", unsafe_allow_html=True)


def value_html(value: Any) -> str:
    if isinstance(value, list):
        items = value or ["Not mentioned in the conversation"]
        return "<ul>" + "".join(f'<li dir="auto">{html.escape(str(item))}</li>' for item in items) + "</ul>"
    return f'<div dir="auto">{html.escape(str(value or "Not mentioned in the conversation"))}</div>'


def render_report(report: dict[str, Any], sections: list[tuple[str, str, str]], kind: str) -> None:
    for key, label, icon in sections:
        st.markdown(
            f"""
            <div class="report-card {kind}">
              <div class="report-title"><span class="report-icon">{icon}</span>{html.escape(label)}</div>
              <div class="report-body">{value_html(report.get(key))}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )


def report_text(title: str, report: dict[str, Any], sections: list[tuple[str, str, str]]) -> str:
    lines = [title, "=" * len(title), ""]
    for key, label, _ in sections:
        lines.append(label)
        lines.append("-" * len(label))
        value = report.get(key)
        if isinstance(value, list):
            lines.extend(f"• {item}" for item in (value or ["Not mentioned in the conversation"]))
        else:
            lines.append(str(value or "Not mentioned in the conversation"))
        lines.append("")
    return "\n".join(lines)


def clear_consultation_state() -> None:
    for key in (
        "transcription",
        "reports",
        "report_mapping",
        "audio_path",
        "doctor_pdf_report",
        "doctor_pdf_path",
        "patient_pdf_report",
        "patient_pdf_path",
        "delivery_token",
        "sent_consultation_id",
    ):
        st.session_state[key] = None


def logout() -> None:
    clear_consultation_state()
    st.session_state.current_user = None


def render_account_header(user: dict[str, Any]) -> None:
    name_column, logout_column = st.columns([5, 1])
    name_column.markdown(
        f"**{html.escape(user['full_name'])}** · {user['role'].title()}"
    )
    if logout_column.button("Logout", use_container_width=True):
        logout()
        st.rerun()


def render_auth_screen() -> None:
    login_tab, register_tab = st.tabs(
        ["Login / تسجيل الدخول", "Create account / إنشاء حساب"]
    )
    with login_tab:
        with st.form("login-form", border=True):
            st.subheader("Welcome back")
            email = st.text_input("Email", autocomplete="email")
            password = st.text_input(
                "Password", type="password", autocomplete="current-password"
            )
            login_submitted = st.form_submit_button(
                "Login", type="primary", use_container_width=True
            )
        if login_submitted:
            try:
                authenticated = authenticate_user(email, password)
                if authenticated is None:
                    st.error("Invalid email or password.")
                else:
                    st.session_state.current_user = authenticated.session_dict()
                    st.rerun()
            except sqlite3.Error:
                st.error("Local account storage is unavailable. Please try again.")

    with register_tab:
        with st.form("registration-form", border=True):
            st.subheader("Create your demo account")
            full_name = st.text_input("Full name")
            email = st.text_input("Email", key="registration-email", autocomplete="email")
            password = st.text_input(
                "Password",
                type="password",
                key="registration-password",
                autocomplete="new-password",
            )
            confirmation = st.text_input(
                "Confirm password",
                type="password",
                autocomplete="new-password",
            )
            role_label = st.selectbox("Role", ["Doctor", "Patient"])
            register_submitted = st.form_submit_button(
                "Create account", type="primary", use_container_width=True
            )
        if register_submitted:
            if password != confirmation:
                st.error("Passwords do not match.")
            else:
                try:
                    register_user(
                        full_name, email, password, role_label.lower()
                    )
                    st.success("Account created. Log in to continue.")
                except AccountError as exc:
                    st.error(str(exc))
                except sqlite3.Error:
                    st.error("Local account storage is unavailable. Please try again.")


def render_patient_dashboard(user: dict[str, Any]) -> None:
    st.markdown('<div class="section-label">Patient dashboard</div>', unsafe_allow_html=True)
    st.subheader("Reports sent to you")
    st.info("No reports have been sent to your account yet.")


st.set_page_config(page_title=APP_NAME, page_icon="⚕", layout="wide", initial_sidebar_state="collapsed")
inject_styles()
initialize_state()
try:
    initialize_database()
except sqlite3.Error:
    st.error("Local account storage is unavailable. Please restart the app.")
    st.stop()

st.markdown(
    """
    <div class="hero">
      <div class="hero-kicker">Medical consultation intelligence</div>
      <h1>Clinical Conversation Companion</h1>
      <p>Turn a doctor–patient conversation into a clear speaker-separated transcript and two useful consultation summaries.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

current_user = st.session_state.current_user
if not current_user:
    render_auth_screen()
    st.stop()

render_account_header(current_user)
if current_user["role"] == "patient":
    render_patient_dashboard(current_user)
    st.stop()

language_choice = st.segmented_control(
    "Consultation language / لغة الاستشارة",
    ["English", "Arabic"],
    default="English",
    format_func=lambda value: "English" if value == "English" else "العربية",
    key="consultation_language",
    on_change=lambda: st.session_state.update(
        transcription=None,
        reports=None,
        report_mapping=None,
        audio_path=None,
        doctor_pdf_report=None,
        doctor_pdf_path=None,
        patient_pdf_report=None,
        patient_pdf_path=None,
    ),
    help="Choose the language spoken in the recording. Reports use the same language.",
    width="stretch",
)
language_choice = language_choice or "English"
language_code = "ara" if language_choice == "Arabic" else "eng"
section_labels = ARABIC_SECTION_LABELS if language_choice == "Arabic" else {}
doctor_sections = [
    (key, section_labels.get(key, label), icon) for key, label, icon in DOCTOR_SECTIONS
]
patient_sections = [
    (key, section_labels.get(key, label), icon) for key, label, icon in PATIENT_SECTIONS
]
doctor_report_title = "تقرير الطبيب" if language_choice == "Arabic" else "Doctor Report"
patient_report_title = "تقرير المريض" if language_choice == "Arabic" else "Patient Report"

active_step = 3 if st.session_state.reports else (2 if st.session_state.transcription else 1)
render_steps(active_step)

st.markdown('<div class="section-label">New consultation</div>', unsafe_allow_html=True)
st.subheader("Add the conversation audio")
st.caption(
    "Upload an existing recording or capture one from your microphone. "
    "The selected language is used for transcription and reports."
)

with st.container(border=True):
    mode = st.radio("Audio source", ["Upload audio", "Record now"], horizontal=True, label_visibility="collapsed")
    if mode == "Upload audio":
        uploaded_file = st.file_uploader(
            "Drop a consultation recording here",
            type=["wav", "mp3", "m4a", "mp4", "mpeg", "mpga", "webm", "ogg"],
            help="Supported: WAV, MP3, M4A, MP4, MPEG, MPGA, WEBM, and OGG — up to 500 MB.",
        )
        recorded_file = None
    else:
        uploaded_file = None
        access_message = microphone_access_message(
            str(st.context.url), bool(st.context.is_embedded)
        )
        if access_message:
            st.warning(access_message)
        st.caption(
            "Click the microphone once to start and again to stop. If it remains at 00:00, "
            "open this page directly in Chrome or Edge and allow microphone access."
        )
        recorded_file = st.audio_input(
            "Record the consultation",
            sample_rate=16000,
            key="consultation_recording",
            help="Your browser will ask for microphone permission the first time.",
        )

    audio_selection = None
    try:
        audio_selection = selected_audio(mode, uploaded_file, recorded_file)
    except StorageError as exc:
        st.error(str(exc))

    if audio_selection:
        preview_name, preview_bytes = audio_selection
        st.audio(preview_bytes)
        st.caption(f"Ready: {preview_name} · {len(preview_bytes) / (1024 * 1024):.1f} MB")

    if st.button("Transcribe conversation", type="primary", use_container_width=True):
        if not audio_selection:
            st.warning("Choose or record an audio conversation first.")
        else:
            try:
                elevenlabs_key, _, _ = require_keys()
                filename, audio_bytes = audio_selection
                with st.status("Transcribing conversation…", expanded=True) as status:
                    st.write("Uploading the recording securely from this local app…")
                    audio_path = save_bytes(AUDIO_DIR, audio_bytes, filename)
                    transcription = transcribe_audio(
                        audio_bytes,
                        filename,
                        elevenlabs_key,
                        language_code=language_code,
                    )
                    neutral_text = neutral_transcript(transcription["turns"], transcription["speaker_ids"])
                    save_text(TRANSCRIPT_DIR, neutral_text, "speaker-transcript")
                    if transcription.get("diarization_fallback_used"):
                        status.write("Speaker separation was strengthened with a second timing pass.")
                    status.write("Speaker-separated transcript is ready.")
                    status.update(label="Transcription complete", state="complete", expanded=False)
                st.session_state.transcription = transcription
                st.session_state.reports = None
                st.session_state.report_mapping = None
                st.session_state.doctor_pdf_report = None
                st.session_state.doctor_pdf_path = None
                st.session_state.patient_pdf_report = None
                st.session_state.patient_pdf_path = None
                st.session_state.audio_path = str(audio_path)
                st.rerun()
            except (StorageError, ServiceError) as exc:
                st.error(str(exc))
            except Exception:
                st.error("Something unexpected interrupted transcription. Please retry with a valid recording.")


transcription = st.session_state.transcription
if transcription:
    st.markdown('<div class="section-label">Speaker review</div>', unsafe_allow_html=True)
    st.subheader("Confirm who is speaking")
    st.caption("Diarization separates voices but does not identify roles. Confirm each label before generating reports.")

    speaker_ids = transcription["speaker_ids"]
    role_columns = st.columns(max(1, len(speaker_ids)))
    mapping: dict[str, str] = {}
    for index, speaker_id in enumerate(speaker_ids):
        with role_columns[index]:
            mapping[speaker_id] = st.selectbox(
                speaker_title(speaker_id, speaker_ids),
                ["Doctor", "Patient"],
                index=0 if index == 0 else 1,
                key=f"role_{speaker_id}",
                format_func=(
                    (lambda role: "الطبيب" if role == "Doctor" else "المريض")
                    if language_choice == "Arabic"
                    else str
                ),
                help="This is a manual label. The application does not infer clinical roles.",
            )

    if len(speaker_ids) < 2:
        st.info("Only one distinct voice was detected. You can still label it, but two-sided reporting may be limited.")
    elif len(set(mapping.values())) != len(mapping.values()):
        st.warning("Assign one speaker as Doctor and the other as Patient before generating reports.")

    labelled_turns = apply_speaker_roles(transcription["turns"], mapping)
    role_transcript = format_transcript(labelled_turns)
    if language_choice == "Arabic":
        role_labels = {"Doctor": "الطبيب", "Patient": "المريض"}
        display_turns = [
            {**turn, "display_role": role_labels.get(str(turn.get("role")), str(turn.get("role")))}
            for turn in labelled_turns
        ]
        transcript_download = format_transcript(
            [
                {**turn, "role": role_labels.get(str(turn.get("role")), str(turn.get("role")))}
                for turn in labelled_turns
            ]
        )
    else:
        display_turns = labelled_turns
        transcript_download = role_transcript

    if st.session_state.reports and st.session_state.report_mapping != mapping:
        st.info("The speaker labels changed. Generate the reports again so they match the updated roles.")

    can_generate = bool(role_transcript.strip()) and (len(speaker_ids) < 2 or len(set(mapping.values())) == len(mapping.values()))
    if st.button("Confirm roles & generate reports", type="primary", use_container_width=True, disabled=not can_generate):
        try:
            _, openrouter_key, model = require_keys()
            with st.status("Analyzing consultation…", expanded=True) as status:
                st.write("Reviewing stated symptoms, history, medicines, tests, and recommendations…")
                status.update(label="Generating reports…", state="running", expanded=True)
                reports = generate_reports(
                    role_transcript,
                    openrouter_key,
                    model=model,
                    output_language=language_choice,
                )
                doctor_download = report_text(
                    doctor_report_title, reports["doctor_report"], doctor_sections
                )
                patient_download = report_text(
                    patient_report_title, reports["patient_report"], patient_sections
                )
                save_text(TRANSCRIPT_DIR, role_transcript, "role-labelled-transcript")
                save_text(REPORT_DIR, doctor_download, "doctor-report")
                save_text(REPORT_DIR, patient_download, "patient-report")
                doctor_pdf_report = build_role_report_pdf(
                    turns=labelled_turns,
                    report=reports["doctor_report"],
                    sections=doctor_sections,
                    audience="doctor",
                    language=language_choice,
                )
                patient_pdf_report = build_role_report_pdf(
                    turns=labelled_turns,
                    report=reports["patient_report"],
                    sections=patient_sections,
                    audience="patient",
                    language=language_choice,
                )
                doctor_pdf_path = save_pdf(
                    REPORT_DIR, doctor_pdf_report, "doctor-consultation-report"
                )
                patient_pdf_path = save_pdf(
                    REPORT_DIR, patient_pdf_report, "patient-consultation-report"
                )
                status.write("Both consultation reports are ready.")
                status.update(label="Reports complete", state="complete", expanded=False)
            st.session_state.reports = reports
            st.session_state.report_mapping = mapping.copy()
            st.session_state.doctor_pdf_report = doctor_pdf_report
            st.session_state.doctor_pdf_path = str(doctor_pdf_path)
            st.session_state.patient_pdf_report = patient_pdf_report
            st.session_state.patient_pdf_path = str(patient_pdf_path)
            st.rerun()
        except (StorageError, ServiceError) as exc:
            st.error(str(exc))
        except Exception:
            st.error("Something unexpected interrupted report generation. Please try again.")

    st.divider()
    results_label = "نتائج الاستشارة" if language_choice == "Arabic" else "Consultation results"
    review_title = "المراجعة والتنزيل" if language_choice == "Arabic" else "Review and download"
    st.markdown(
        f'<div class="section-label">{results_label}</div>', unsafe_allow_html=True
    )
    st.subheader(review_title)

    language = transcription.get("language_code") or (
        "غير محددة" if language_choice == "Arabic" else "Not provided"
    )
    confidence = transcription.get("language_probability")
    confidence_text = (
        f"{confidence:.0%}"
        if isinstance(confidence, (float, int))
        else ("غير متاحة" if language_choice == "Arabic" else "Not provided")
    )
    language_label = "اللغة" if language_choice == "Arabic" else "Language"
    confidence_label = (
        "دقة تحديد اللغة" if language_choice == "Arabic" else "Language confidence"
    )
    turns_label = "عدد المقاطع" if language_choice == "Arabic" else "Turns"
    st.markdown(
        f'<div class="meta-row"><span class="meta-pill">{language_label} · {html.escape(str(language).upper())}</span>'
        f'<span class="meta-pill">{confidence_label} · {confidence_text}</span>'
        f'<span class="meta-pill">{turns_label} · {len(labelled_turns)}</span></div>',
        unsafe_allow_html=True,
    )

    reports_current = st.session_state.reports and st.session_state.report_mapping == mapping
    if reports_current:
        tab_labels = (
            ["النص", "تقرير الطبيب", "تقرير المريض"]
            if language_choice == "Arabic"
            else ["Transcript", "Doctor Report", "Patient Report"]
        )
        transcript_tab, doctor_tab, patient_tab = st.tabs(tab_labels)
    else:
        (transcript_tab,) = st.tabs([
            "النص" if language_choice == "Arabic" else "Transcript"
        ])
        doctor_tab = patient_tab = None

    with transcript_tab:
        render_transcript(display_turns)
        st.download_button(
            "تنزيل النص بصيغة TXT"
            if language_choice == "Arabic"
            else "Download transcript as TXT",
            data=transcript_download.encode("utf-8"),
            file_name="consultation-transcript.txt",
            mime="text/plain",
            use_container_width=True,
        )

    if reports_current and doctor_tab and patient_tab:
        reports = st.session_state.reports
        with doctor_tab:
            st.caption(
                "توثيق موجّه للطبيب ومُنشأ فقط من المحادثة المسجلة."
                if language_choice == "Arabic"
                else "Clinician-facing documentation generated only from the recorded conversation."
            )
            render_report(reports["doctor_report"], doctor_sections, "doctor")
            doctor_download = report_text(
                doctor_report_title, reports["doctor_report"], doctor_sections
            )
            st.download_button(
                "تنزيل تقرير الطبيب" if language_choice == "Arabic" else "Download doctor report",
                data=doctor_download.encode("utf-8"),
                file_name="doctor-report.txt",
                mime="text/plain",
                use_container_width=True,
            )
            if st.session_state.doctor_pdf_report:
                st.download_button(
                    "تنزيل تقرير الطبيب بصيغة PDF"
                    if language_choice == "Arabic"
                    else "Download doctor PDF report",
                    data=st.session_state.doctor_pdf_report,
                    file_name="doctor-consultation-report.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
        with patient_tab:
            st.caption(
                "ملخص بلغة بسيطة. اتبع تعليمات الطبيب المباشرة إذا اختلفت عن هذا الملخص."
                if language_choice == "Arabic"
                else "A plain-language recap. Follow the clinician's direct advice if it differs from this summary."
            )
            render_report(reports["patient_report"], patient_sections, "patient")
            patient_download = report_text(
                patient_report_title, reports["patient_report"], patient_sections
            )
            st.download_button(
                "تنزيل تقرير المريض" if language_choice == "Arabic" else "Download patient report",
                data=patient_download.encode("utf-8"),
                file_name="patient-report.txt",
                mime="text/plain",
                use_container_width=True,
            )
            if st.session_state.patient_pdf_report:
                st.download_button(
                    "تنزيل تقرير المريض بصيغة PDF"
                    if language_choice == "Arabic"
                    else "Download patient PDF report",
                    data=st.session_state.patient_pdf_report,
                    file_name="patient-consultation-report.pdf",
                    mime="application/pdf",
                    type="primary",
                    use_container_width=True,
                )
