from pathlib import Path

from streamlit.testing.v1 import AppTest

import accounts


def _app_path() -> Path:
    return Path(__file__).resolve().parents[1] / "app.py"


def _database(monkeypatch, tmp_path: Path) -> Path:
    db = tmp_path / "app.db"
    monkeypatch.setenv("MEDICAL_APP_DB", str(db))
    accounts.initialize_database(db)
    return db


def _authenticated_app(monkeypatch, tmp_path: Path, role: str):
    db = _database(monkeypatch, tmp_path)
    user = accounts.register_user(
        f"Demo {role.title()}", f"{role}@example.com", "password-1", role, db
    )
    app = AppTest.from_file(_app_path()).run(timeout=20)
    app.session_state["current_user"] = user.session_dict()
    return app.run(timeout=20), user, db


def test_logged_out_view_shows_login_and_registration(monkeypatch, tmp_path):
    _database(monkeypatch, tmp_path)
    app = AppTest.from_file(_app_path()).run(timeout=20)
    assert [tab.label for tab in app.tabs] == [
        "Login / تسجيل الدخول",
        "Create account / إنشاء حساب",
    ]
    assert len(app.get("button_group")) == 0
    assert len(app.exception) == 0


def test_doctor_route_contains_consultation_workflow(monkeypatch, tmp_path):
    app, _, _ = _authenticated_app(monkeypatch, tmp_path, "doctor")
    assert app.get("button_group")[0].value == "English"
    assert any(button.label == "Logout" for button in app.button)
    assert len(app.exception) == 0


def test_patient_route_hides_consultation_workflow(monkeypatch, tmp_path):
    app, _, _ = _authenticated_app(monkeypatch, tmp_path, "patient")
    assert len(app.get("button_group")) == 0
    assert "Reports sent to you" in [heading.value for heading in app.subheader]
    assert len(app.exception) == 0


def test_language_toggle_defaults_to_english_and_can_switch_to_arabic(
    monkeypatch, tmp_path
):
    app, _, _ = _authenticated_app(monkeypatch, tmp_path, "doctor")

    controls = app.get("button_group")
    assert len(controls) == 1
    assert controls[0].value == "English"

    app.session_state["transcription"] = {"old": "transcript"}
    app.session_state["reports"] = {"old": "reports"}
    app.session_state["report_mapping"] = {"speaker_0": "Doctor"}
    app.session_state["audio_path"] = "old.wav"

    controls[0].set_value("Arabic").run(timeout=20)

    assert app.get("button_group")[0].value == "Arabic"
    assert app.session_state["transcription"] is None
    assert app.session_state["reports"] is None
    assert app.session_state["report_mapping"] is None
    assert app.session_state["audio_path"] is None
    assert len(app.exception) == 0


def test_arabic_mode_localizes_transcript_roles_and_result_metadata(
    monkeypatch, tmp_path
):
    app, _, _ = _authenticated_app(monkeypatch, tmp_path, "doctor")
    app.get("button_group")[0].set_value("Arabic").run(timeout=20)
    app.session_state["transcription"] = {
        "speaker_ids": ["speaker_0", "speaker_1"],
        "turns": [
            {"speaker_id": "speaker_0", "text": "مرحباً", "start": 0.0, "end": 1.0},
            {"speaker_id": "speaker_1", "text": "أشعر بصداع", "start": 1.1, "end": 2.0},
        ],
        "language_code": "ara",
        "language_probability": 0.99,
    }

    app.run(timeout=20)

    rendered_html = "\n".join(element.value for element in app.markdown)
    assert "الطبيب" in rendered_html
    assert "المريض" in rendered_html
    assert "اللغة" in rendered_html
    assert "عدد المقاطع" in rendered_html
    assert len(app.exception) == 0


def test_separate_doctor_and_patient_pdf_downloads_appear_when_reports_are_ready(
    monkeypatch, tmp_path
):
    app, _, _ = _authenticated_app(monkeypatch, tmp_path, "doctor")
    app.session_state["transcription"] = {
        "speaker_ids": ["speaker_0", "speaker_1"],
        "turns": [
            {"speaker_id": "speaker_0", "text": "Hello", "start": 0.0, "end": 1.0},
            {"speaker_id": "speaker_1", "text": "Headache", "start": 1.1, "end": 2.0},
        ],
        "language_code": "eng",
        "language_probability": 0.99,
    }
    app.session_state["reports"] = {"doctor_report": {}, "patient_report": {}}
    app.session_state["report_mapping"] = {
        "speaker_0": "Doctor",
        "speaker_1": "Patient",
    }
    app.session_state["doctor_pdf_report"] = b"%PDF-doctor"
    app.session_state["doctor_pdf_path"] = "data/reports/doctor-consultation-report.pdf"
    app.session_state["patient_pdf_report"] = b"%PDF-patient"
    app.session_state["patient_pdf_path"] = "data/reports/patient-consultation-report.pdf"

    app.run(timeout=20)

    labels = [button.label for button in app.get("download_button")]
    assert "Download doctor PDF report" in labels
    assert "Download patient PDF report" in labels
    assert "Download complete PDF report" not in labels
    assert len(app.exception) == 0


def test_doctor_can_select_registered_patient_and_send_ready_reports(
    monkeypatch, tmp_path
):
    app, doctor, db = _authenticated_app(monkeypatch, tmp_path, "doctor")
    patient = accounts.register_user(
        "Mona Patient", "mona@example.com", "password-2", "patient", db
    )
    app.session_state["transcription"] = {
        "speaker_ids": ["speaker_0", "speaker_1"],
        "turns": [
            {"speaker_id": "speaker_0", "text": "Hello", "start": 0.0, "end": 1.0},
            {
                "speaker_id": "speaker_1",
                "text": "Headache",
                "start": 1.1,
                "end": 2.0,
            },
        ],
        "language_code": "eng",
        "language_probability": 0.99,
    }
    app.session_state["reports"] = {
        "doctor_report": {"consultation_summary": "Headache discussed."},
        "patient_report": {"what_was_discussed": "Your headache."},
    }
    app.session_state["report_mapping"] = {
        "speaker_0": "Doctor",
        "speaker_1": "Patient",
    }
    app.session_state["doctor_pdf_report"] = b"%PDF-doctor"
    app.session_state["doctor_pdf_path"] = "data/reports/doctor.pdf"
    app.session_state["patient_pdf_report"] = b"%PDF-patient"
    app.session_state["patient_pdf_path"] = "data/reports/patient.pdf"
    app.session_state["delivery_token"] = "delivery-1"
    app.session_state["audio_path"] = "data/audio/visit.wav"
    app.run(timeout=20)

    patient_selector = next(
        box for box in app.selectbox if box.label == "Send report to patient"
    )
    patient_selector.set_value(patient.id).run(timeout=20)
    next(
        button for button in app.button if button.label == "Send to patient"
    ).click().run(timeout=20)

    history = accounts.list_doctor_consultations(doctor.id, db)
    assert len(history) == 1
    assert history[0]["patient_email"] == "mona@example.com"


def test_doctor_history_survives_missing_pdf_files(monkeypatch, tmp_path):
    app, doctor, db = _authenticated_app(monkeypatch, tmp_path, "doctor")
    patient = accounts.register_user(
        "Mona", "mona@example.com", "password-2", "patient", db
    )
    accounts.send_consultation(
        doctor_id=doctor.id,
        patient_id=patient.id,
        delivery_token="delivery-1",
        language="English",
        transcript="Doctor: Hello",
        doctor_report={"consultation_summary": "Clinical summary"},
        patient_report={"what_was_discussed": "Patient summary"},
        doctor_pdf_path="missing-doctor.pdf",
        patient_pdf_path="missing-patient.pdf",
        audio_path=None,
        db_path=db,
    )
    app.run(timeout=20)
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Clinical summary" in rendered
    assert "Patient summary" in rendered
    assert "PDF file is no longer available" in rendered
    assert len(app.exception) == 0


def test_patient_sees_only_own_patient_report(monkeypatch, tmp_path):
    app, patient, db = _authenticated_app(monkeypatch, tmp_path, "patient")
    doctor = accounts.register_user(
        "Dr. Sara", "doctor2@example.com", "password-2", "doctor", db
    )
    accounts.send_consultation(
        doctor_id=doctor.id,
        patient_id=patient.id,
        delivery_token="delivery-1",
        language="English",
        transcript="Doctor: Hello",
        doctor_report={"consultation_summary": "Doctor-only wording"},
        patient_report={"what_was_discussed": "Patient-friendly wording"},
        doctor_pdf_path="data/reports/doctor.pdf",
        patient_pdf_path="missing-patient.pdf",
        audio_path=None,
        db_path=db,
    )

    app.run(timeout=20)
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Patient-friendly wording" in rendered
    assert "Doctor-only wording" not in rendered
    assert "PDF file is no longer available" in rendered
    assert len(app.exception) == 0


def test_patient_empty_state_does_not_show_other_patients_reports(
    monkeypatch, tmp_path
):
    app, patient, db = _authenticated_app(monkeypatch, tmp_path, "patient")
    doctor = accounts.register_user(
        "Dr. Sara", "doctor2@example.com", "password-2", "doctor", db
    )
    other_patient = accounts.register_user(
        "Other", "other@example.com", "password-3", "patient", db
    )
    accounts.send_consultation(
        doctor_id=doctor.id,
        patient_id=other_patient.id,
        delivery_token="delivery-2",
        language="English",
        transcript="Doctor: Private",
        doctor_report={"consultation_summary": "Private doctor report"},
        patient_report={"what_was_discussed": "Other patient's report"},
        doctor_pdf_path="doctor.pdf",
        patient_pdf_path="patient.pdf",
        audio_path=None,
        db_path=db,
    )
    app.run(timeout=20)
    assert any("No reports have been sent" in item.value for item in app.info)
    rendered = "\n".join(item.value for item in app.markdown)
    assert "Other patient's report" not in rendered
