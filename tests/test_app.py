from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_language_toggle_defaults_to_english_and_can_switch_to_arabic():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(app_path).run(timeout=20)

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


def test_arabic_mode_localizes_transcript_roles_and_result_metadata():
    app_path = Path(__file__).resolve().parents[1] / "app.py"
    app = AppTest.from_file(app_path).run(timeout=20)
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
