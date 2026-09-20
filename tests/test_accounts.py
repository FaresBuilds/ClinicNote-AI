from pathlib import Path

import pytest

import accounts


def test_register_and_authenticate_normalizes_email_and_hides_password(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)

    created = accounts.register_user(
        "Dr. Sara", " Sara@Example.com ", "safe-pass-123", "doctor", db
    )
    authenticated = accounts.authenticate_user(
        "sara@example.com", "safe-pass-123", db
    )

    assert created.email == "sara@example.com"
    assert authenticated == created
    with accounts.connect(db) as connection:
        row = connection.execute(
            "SELECT password_hash, password_salt FROM users WHERE id = ?",
            (created.id,),
        ).fetchone()
    assert row["password_hash"] != "safe-pass-123"
    assert row["password_salt"]


def test_duplicate_email_is_rejected_case_insensitively(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    accounts.register_user(
        "Patient One", "patient@example.com", "password-1", "patient", db
    )

    with pytest.raises(accounts.DuplicateEmailError):
        accounts.register_user(
            "Patient Two", " PATIENT@example.com ", "password-2", "patient", db
        )


@pytest.mark.parametrize(
    ("email", "password"),
    [("missing@example.com", "password-1"), ("patient@example.com", "wrong-pass")],
)
def test_invalid_login_returns_none_without_revealing_which_field_failed(
    tmp_path: Path, email: str, password: str
):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    accounts.register_user(
        "Patient", "patient@example.com", "password-1", "patient", db
    )
    assert accounts.authenticate_user(email, password, db) is None


@pytest.mark.parametrize(
    ("name", "email", "password", "role"),
    [
        ("", "person@example.com", "password-1", "patient"),
        ("Person", "not-an-email", "password-1", "patient"),
        ("Person", "person@example.com", "short", "patient"),
        ("Person", "person@example.com", "password-1", "admin"),
    ],
)
def test_registration_rejects_invalid_fields(
    tmp_path: Path, name: str, email: str, password: str, role: str
):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    with pytest.raises(accounts.AccountError):
        accounts.register_user(name, email, password, role, db)


def _registered_users(db: Path):
    doctor = accounts.register_user(
        "Dr. Sara", "doctor@example.com", "password-1", "doctor", db
    )
    other_doctor = accounts.register_user(
        "Dr. Omar", "other@example.com", "password-2", "doctor", db
    )
    patient = accounts.register_user(
        "Mona", "patient@example.com", "password-3", "patient", db
    )
    other_patient = accounts.register_user(
        "Ali", "other-patient@example.com", "password-4", "patient", db
    )
    return doctor, other_doctor, patient, other_patient


def test_doctor_sends_once_and_keeps_both_reports(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    doctor, _, patient, _ = _registered_users(db)
    payload = dict(
        doctor_id=doctor.id,
        patient_id=patient.id,
        delivery_token="consultation-token-1",
        language="English",
        transcript="Doctor: Hello\nPatient: Headache",
        doctor_report={"consultation_summary": "Headache discussed."},
        patient_report={"what_was_discussed": "Your headache."},
        doctor_pdf_path="data/reports/doctor.pdf",
        patient_pdf_path="data/reports/patient.pdf",
        audio_path="data/audio/visit.wav",
        db_path=db,
    )

    first_id = accounts.send_consultation(**payload)
    second_id = accounts.send_consultation(**payload)
    history = accounts.list_doctor_consultations(doctor.id, db)

    assert first_id == second_id
    assert len(history) == 1
    assert history[0]["doctor_report"]["consultation_summary"] == "Headache discussed."
    assert history[0]["patient_report"]["what_was_discussed"] == "Your headache."


def test_patient_history_excludes_doctor_only_data_and_other_accounts(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    doctor, other_doctor, patient, other_patient = _registered_users(db)
    consultation_id = accounts.send_consultation(
        doctor_id=doctor.id,
        patient_id=patient.id,
        delivery_token="consultation-token-1",
        language="Arabic",
        transcript="الطبيب: مرحباً",
        doctor_report={"consultation_summary": "ملخص سريري"},
        patient_report={"what_was_discussed": "تمت مناقشة الصداع"},
        doctor_pdf_path="data/reports/doctor.pdf",
        patient_pdf_path="data/reports/patient.pdf",
        audio_path=None,
        db_path=db,
    )

    patient_history = accounts.list_patient_consultations(patient.id, db)
    assert [item["id"] for item in patient_history] == [consultation_id]
    assert "doctor_report" not in patient_history[0]
    assert "doctor_pdf_path" not in patient_history[0]
    assert accounts.list_patient_consultations(other_patient.id, db) == []
    assert accounts.list_doctor_consultations(other_doctor.id, db) == []


def test_only_doctors_can_send_to_patient_accounts(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    doctor, _, patient, other_patient = _registered_users(db)
    base = dict(
        delivery_token="token",
        language="English",
        transcript="Transcript",
        doctor_report={},
        patient_report={},
        doctor_pdf_path="doctor.pdf",
        patient_pdf_path="patient.pdf",
        audio_path=None,
        db_path=db,
    )
    with pytest.raises(accounts.AuthorizationError):
        accounts.send_consultation(
            doctor_id=patient.id, patient_id=other_patient.id, **base
        )
    with pytest.raises(accounts.AuthorizationError):
        accounts.send_consultation(doctor_id=doctor.id, patient_id=doctor.id, **base)


def test_list_patients_returns_only_patient_accounts(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    _, _, patient, other_patient = _registered_users(db)
    assert accounts.list_patients(db) == [other_patient, patient]
