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
