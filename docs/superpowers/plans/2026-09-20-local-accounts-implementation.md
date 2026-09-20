# Local Doctor and Patient Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add self-registered Doctor and Patient accounts, local login, doctor-to-patient report delivery, and role-filtered consultation histories to the existing Streamlit demo.

**Architecture:** Add one focused `accounts.py` module backed by Python's built-in SQLite and password-hashing libraries. Keep authentication state in Streamlit session state, keep the existing transcription/report/PDF pipeline, and persist only completed consultations after an explicit doctor send action. Route authenticated doctors to the consultation workflow plus their history, and patients to a read-only patient-report history.

**Tech Stack:** Python 3.12+, Streamlit, standard-library `sqlite3`, PBKDF2-HMAC-SHA256 via `hashlib`, pytest, existing ReportLab PDF pipeline.

**Spec:** `docs/superpowers/specs/2026-09-20-local-accounts-design.md`

## Global Constraints

- Store the demo database at `data/medical_app.db` by default.
- Allow tests to override the database location with `MEDICAL_APP_DB`.
- Store only salted password hashes; never store or log plaintext passwords.
- Roles are exactly `doctor` and `patient`.
- Only doctors create and send consultations.
- Doctors retain Doctor and Patient reports; patients receive only the Patient Report and Patient PDF.
- Preserve English and Arabic behavior throughout account screens and report history.
- Use no ORM, external authentication provider, email verification, password reset, admin system, or permanent cloud storage.
- Treat local data loss after a Streamlit Community Cloud restart as acceptable for this demo.
- Preserve the existing ElevenLabs, OpenRouter, transcript, report, PDF, and local-file behavior.

## Review Focus

- Email case and surrounding whitespace: `Patient@Example.com` and ` patient@example.com ` must identify one account; Task 1 pins this with a duplicate-registration test.
- Authentication leakage: an unknown email and a wrong password must return the same safe failure result; Task 1 pins both cases.
- Cross-account access: one doctor or patient must never read another user's consultation; Task 2 pins ownership filtering and the patient projection.
- Repeated send clicks: one generated consultation must create only one database row; Task 2 pins idempotency by delivery token.
- Missing local PDFs after a cloud reset: histories must still render report text and show a friendly unavailable message instead of crashing; Tasks 4 and 5 pin this UI behavior.

---

## File Structure

- Create `accounts.py`: SQLite schema, account validation, password hashing, authentication, patient lookup, idempotent consultation delivery, and role-filtered history queries.
- Create `tests/test_accounts.py`: real temporary SQLite tests for authentication, authorization, delivery, and history projections.
- Modify `app.py`: authentication screens, session routing, Doctor dashboard, patient selection/send controls, and both history views.
- Modify `tests/test_app.py`: authenticated AppTest helpers plus login, role-routing, send-control, and history tests.
- Modify `.gitignore`: ignore `data/medical_app.db` and SQLite journal files.
- Modify `README.md`: document demo accounts, Streamlit Secrets, ephemeral Community Cloud storage, and the doctor-to-patient demonstration flow.

### Task 1: SQLite Accounts and Authentication

**Files:**
- Create: `accounts.py`
- Create: `tests/test_accounts.py`

**Interfaces:**
- Consumes: optional `db_path: str | Path | None`; `None` resolves `MEDICAL_APP_DB` or `data/medical_app.db`.
- Produces: `AccountError`, `DuplicateEmailError`, `User`, `initialize_database()`, `register_user()`, and `authenticate_user()`.

- [ ] **Step 1: Write failing account tests**

Create `tests/test_accounts.py` with real temporary databases:

```python
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
    accounts.register_user("Patient One", "patient@example.com", "password-1", "patient", db)

    with pytest.raises(accounts.DuplicateEmailError):
        accounts.register_user("Patient Two", " PATIENT@example.com ", "password-2", "patient", db)


@pytest.mark.parametrize(
    ("email", "password"),
    [("missing@example.com", "password-1"), ("patient@example.com", "wrong-pass")],
)
def test_invalid_login_returns_none_without_revealing_which_field_failed(
    tmp_path: Path, email: str, password: str
):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    accounts.register_user("Patient", "patient@example.com", "password-1", "patient", db)
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
```

- [ ] **Step 2: Run tests and verify the missing module failure**

Run: `python -m pytest tests/test_accounts.py -q`

Expected: collection fails because `accounts` does not exist.

- [ ] **Step 3: Implement the account schema and hashing boundary**

Create `accounts.py` with these public types and helpers:

```python
from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import sqlite3
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PBKDF2_ITERATIONS = 310_000
VALID_ROLES = {"doctor", "patient"}
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


class AccountError(ValueError):
    """Safe account or consultation validation error."""


class DuplicateEmailError(AccountError):
    """The normalized email is already registered."""


class AuthorizationError(AccountError):
    """The current account cannot perform the requested action."""


@dataclass(frozen=True)
class User:
    id: int
    full_name: str
    email: str
    role: str

    def session_dict(self) -> dict[str, Any]:
        return asdict(self)


def database_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path or os.getenv("MEDICAL_APP_DB", "data/medical_app.db"))


def connect(db_path: str | Path | None = None) -> sqlite3.Connection:
    path = database_path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database(db_path: str | Path | None = None) -> None:
    with connect(db_path) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('doctor', 'patient')),
                created_at TEXT NOT NULL
            );
            """
        )


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()
```

Implement validation, registration, and authentication as follows:

```python
def _normalized_email(email: str) -> str:
    normalized = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(normalized):
        raise AccountError("Enter a valid email address.")
    return normalized


def _user_from_row(row: sqlite3.Row) -> User:
    return User(
        id=int(row["id"]),
        full_name=str(row["full_name"]),
        email=str(row["email"]),
        role=str(row["role"]),
    )


def register_user(
    full_name: str,
    email: str,
    password: str,
    role: str,
    db_path: str | Path | None = None,
) -> User:
    name = full_name.strip()
    normalized = _normalized_email(email)
    if not name:
        raise AccountError("Enter your full name.")
    if len(password) < 8:
        raise AccountError("Password must contain at least 8 characters.")
    if role not in VALID_ROLES:
        raise AccountError("Choose Doctor or Patient.")
    salt = secrets.token_bytes(16)
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        with connect(db_path) as connection:
            cursor = connection.execute(
                """INSERT INTO users
                   (full_name, email, password_hash, password_salt, role, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (name, normalized, _hash_password(password, salt), salt.hex(), role, created_at),
            )
            row = connection.execute(
                "SELECT id, full_name, email, role FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise DuplicateEmailError("An account with this email already exists.") from exc
    return _user_from_row(row)


def authenticate_user(
    email: str,
    password: str,
    db_path: str | Path | None = None,
) -> User | None:
    try:
        normalized = _normalized_email(email)
    except AccountError:
        return None
    with connect(db_path) as connection:
        row = connection.execute(
            """SELECT id, full_name, email, role, password_hash, password_salt
               FROM users WHERE email = ?""",
            (normalized,),
        ).fetchone()
    if row is None:
        return None
    candidate = _hash_password(password, bytes.fromhex(row["password_salt"]))
    if not hmac.compare_digest(candidate, row["password_hash"]):
        return None
    return _user_from_row(row)
```

Normalize email with `email.strip().lower()`, validate name/email/password/role before opening the transaction, generate `secrets.token_bytes(16)`, and compare login hashes with `hmac.compare_digest`. Convert SQLite unique-email failures to `DuplicateEmailError("An account with this email already exists.")`.

- [ ] **Step 4: Run account tests**

Run: `python -m pytest tests/test_accounts.py -q`

Expected: all Task 1 tests pass.

- [ ] **Step 5: Commit Task 1**

```powershell
git add accounts.py tests/test_accounts.py
git commit -m "feat: add local account authentication"
```

### Task 2: Consultation Delivery and Role-Filtered Histories

**Files:**
- Modify: `accounts.py`
- Modify: `tests/test_accounts.py`

**Interfaces:**
- Consumes: `User`, existing report dictionaries, saved artifact paths, and a stable `delivery_token` created when reports are generated.
- Produces: `list_patients()`, `send_consultation()`, `list_doctor_consultations()`, and `list_patient_consultations()`.

- [ ] **Step 1: Add failing delivery and permission tests**

Append to `tests/test_accounts.py`:

```python
def _registered_users(db: Path):
    doctor = accounts.register_user("Dr. Sara", "doctor@example.com", "password-1", "doctor", db)
    other_doctor = accounts.register_user("Dr. Omar", "other@example.com", "password-2", "doctor", db)
    patient = accounts.register_user("Mona", "patient@example.com", "password-3", "patient", db)
    other_patient = accounts.register_user("Ali", "other-patient@example.com", "password-4", "patient", db)
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
        accounts.send_consultation(doctor_id=patient.id, patient_id=other_patient.id, **base)
    with pytest.raises(accounts.AuthorizationError):
        accounts.send_consultation(doctor_id=doctor.id, patient_id=doctor.id, **base)


def test_list_patients_returns_only_patient_accounts(tmp_path: Path):
    db = tmp_path / "accounts.db"
    accounts.initialize_database(db)
    _, _, patient, other_patient = _registered_users(db)
    assert accounts.list_patients(db) == [other_patient, patient]
```

- [ ] **Step 2: Run the new tests and verify missing schema/functions**

Run: `python -m pytest tests/test_accounts.py -q`

Expected: failures identify the missing consultation table and public functions.

- [ ] **Step 3: Extend the schema and implement delivery**

Add this table and indexes to `initialize_database()`:

```sql
CREATE TABLE IF NOT EXISTS consultations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    doctor_id INTEGER NOT NULL REFERENCES users(id),
    patient_id INTEGER NOT NULL REFERENCES users(id),
    delivery_token TEXT NOT NULL UNIQUE,
    language TEXT NOT NULL CHECK (language IN ('English', 'Arabic')),
    transcript TEXT NOT NULL,
    doctor_report_json TEXT NOT NULL,
    patient_report_json TEXT NOT NULL,
    doctor_pdf_path TEXT NOT NULL,
    patient_pdf_path TEXT NOT NULL,
    audio_path TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS consultations_doctor_idx
    ON consultations(doctor_id, sent_at DESC);
CREATE INDEX IF NOT EXISTS consultations_patient_idx
    ON consultations(patient_id, sent_at DESC);
```

Implement the exact public functions below. Import `json` at the top of `accounts.py`.

```python
def list_patients(db_path: str | Path | None = None) -> list[User]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT id, full_name, email, role FROM users
               WHERE role = 'patient' ORDER BY lower(full_name), email"""
        ).fetchall()
    return [_user_from_row(row) for row in rows]


def send_consultation(
    *,
    doctor_id: int,
    patient_id: int,
    delivery_token: str,
    language: str,
    transcript: str,
    doctor_report: dict[str, Any],
    patient_report: dict[str, Any],
    doctor_pdf_path: str,
    patient_pdf_path: str,
    audio_path: str | None,
    db_path: str | Path | None = None,
) -> int:
    with connect(db_path) as connection:
        users = connection.execute(
            "SELECT id, role FROM users WHERE id IN (?, ?)",
            (doctor_id, patient_id),
        ).fetchall()
        roles = {int(row["id"]): row["role"] for row in users}
        if roles.get(doctor_id) != "doctor" or roles.get(patient_id) != "patient":
            raise AuthorizationError("Only doctors can send reports to patient accounts.")
        if language not in {"English", "Arabic"} or not transcript.strip():
            raise AccountError("The consultation is incomplete and cannot be sent.")
        now = datetime.now(timezone.utc).isoformat()
        connection.execute(
            """INSERT INTO consultations
               (doctor_id, patient_id, delivery_token, language, transcript,
                doctor_report_json, patient_report_json, doctor_pdf_path,
                patient_pdf_path, audio_path, created_at, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(delivery_token) DO NOTHING""",
            (
                doctor_id, patient_id, delivery_token, language, transcript,
                json.dumps(doctor_report, ensure_ascii=False),
                json.dumps(patient_report, ensure_ascii=False),
                doctor_pdf_path, patient_pdf_path, audio_path, now, now,
            ),
        )
        row = connection.execute(
            "SELECT id, doctor_id, patient_id FROM consultations WHERE delivery_token = ?",
            (delivery_token,),
        ).fetchone()
        if row["doctor_id"] != doctor_id or row["patient_id"] != patient_id:
            raise AuthorizationError("This consultation was already sent to another account.")
        return int(row["id"])


def list_doctor_consultations(
    doctor_id: int, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT c.id, c.language, c.transcript, c.doctor_report_json,
                      c.patient_report_json, c.doctor_pdf_path, c.patient_pdf_path,
                      c.audio_path, c.sent_at, u.full_name AS patient_name,
                      u.email AS patient_email
               FROM consultations c JOIN users u ON u.id = c.patient_id
               WHERE c.doctor_id = ? ORDER BY c.sent_at DESC, c.id DESC""",
            (doctor_id,),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["doctor_report"] = json.loads(item.pop("doctor_report_json"))
        item["patient_report"] = json.loads(item.pop("patient_report_json"))
        results.append(item)
    return results


def list_patient_consultations(
    patient_id: int, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    with connect(db_path) as connection:
        rows = connection.execute(
            """SELECT c.id, c.language, c.patient_report_json,
                      c.patient_pdf_path, c.sent_at,
                      u.full_name AS doctor_name, u.email AS doctor_email
               FROM consultations c JOIN users u ON u.id = c.doctor_id
               WHERE c.patient_id = ? ORDER BY c.sent_at DESC, c.id DESC""",
            (patient_id,),
        ).fetchall()
    results = []
    for row in rows:
        item = dict(row)
        item["patient_report"] = json.loads(item.pop("patient_report_json"))
        results.append(item)
    return results
```

The patient history SQL deliberately selects only patient-safe columns; do not fetch and then delete Doctor fields in Python.

- [ ] **Step 4: Run all account tests**

Run: `python -m pytest tests/test_accounts.py -q`

Expected: all Task 1 and Task 2 tests pass.

- [ ] **Step 5: Commit Task 2**

```powershell
git add accounts.py tests/test_accounts.py
git commit -m "feat: persist sent consultations by account"
```

### Task 3: Login, Registration, Logout, and Role Routing

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `initialize_database()`, `register_user()`, `authenticate_user()`, `User.session_dict()`.
- Produces: `st.session_state.current_user`, unauthenticated account forms, logout behavior, and Doctor/Patient route boundaries.

- [ ] **Step 1: Add authenticated AppTest helpers and failing route tests**

At the top of `tests/test_app.py`, import the account functions and add:

```python
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
```

Add route tests:

```python
def test_logged_out_view_shows_login_and_registration(monkeypatch, tmp_path):
    _database(monkeypatch, tmp_path)
    app = AppTest.from_file(_app_path()).run(timeout=20)
    assert [tab.label for tab in app.tabs] == [
        "Login / تسجيل الدخول", "Create account / إنشاء حساب"
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
```

Update the existing language and report-result AppTests to call `_authenticated_app(monkeypatch, tmp_path, "doctor")` instead of starting from an unauthenticated application.

- [ ] **Step 2: Run app tests and verify unauthenticated routing failures**

Run: `python -m pytest tests/test_app.py -q`

Expected: the account entry screen and role routing assertions fail.

- [ ] **Step 3: Implement session state and account forms**

Import account APIs in `app.py` and add these state defaults:

```python
"current_user": None,
"delivery_token": None,
"sent_consultation_id": None,
```

Import `sqlite3`, call `initialize_database()` once at startup, and convert initialization failure into a generic `Local account storage is unavailable. Please restart the app.` message followed by `st.stop()`; never render the raw exception. Add these UI helpers above the top-level rendering code:

```python
def clear_consultation_state() -> None:
    for key in (
        "transcription", "reports", "report_mapping", "audio_path",
        "doctor_pdf_report", "doctor_pdf_path", "patient_pdf_report",
        "patient_pdf_path", "delivery_token", "sent_consultation_id",
    ):
        st.session_state[key] = None


def logout() -> None:
    clear_consultation_state()
    st.session_state.current_user = None


def render_account_header(user: dict[str, Any]) -> None:
    name_column, logout_column = st.columns([5, 1])
    name_column.markdown(f"**{html.escape(user['full_name'])}** · {user['role'].title()}")
    if logout_column.button("Logout", use_container_width=True):
        logout()
        st.rerun()
```

Implement `render_auth_screen()` with bilingual tab labels `Login / تسجيل الدخول` and `Create account / إنشاء حساب`. The Login form has Email and Password fields and calls `authenticate_user()`. The registration form has Full name, Email, Password, Confirm password, and Role fields, checks confirmation equality, and calls `register_user()`. Successful registration uses `st.success("Account created. Log in to continue.")`; invalid credentials use the single message `Invalid email or password.`. Catch `AccountError` for safe validation text and catch `sqlite3.Error` with the generic message `Local account storage is unavailable. Please try again.`.

Use `st.form` for Login and Create Account. Registration requires password confirmation before calling `register_user()`. Login stores `authenticated.session_dict()` and reruns. Both forms catch `AccountError` and use `st.error()` without stack traces.

After rendering the hero, route before any consultation controls:

```python
current_user = st.session_state.current_user
if not current_user:
    render_auth_screen()
    st.stop()

render_account_header(current_user)
if current_user["role"] == "patient":
    render_patient_dashboard(current_user)
    st.stop()
```

Initially implement `render_patient_dashboard()` as an empty-state panel saying that no reports have been sent yet. Keep all existing consultation UI on the Doctor route.

- [ ] **Step 4: Run app tests**

Run: `python -m pytest tests/test_app.py -q`

Expected: authentication entry, Doctor route, Patient route, and existing Doctor workflow tests pass.

- [ ] **Step 5: Commit Task 3**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: add account screens and role routing"
```

### Task 4: Doctor Patient Selection, Sending, and History

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `list_patients()`, `send_consultation()`, `list_doctor_consultations()`, completed report/PDF session state, and the logged-in Doctor ID.
- Produces: explicit patient selection, idempotent Send to Patient action, `localized_sections()`, and Doctor History showing both reports.

- [ ] **Step 1: Add failing Doctor send/history UI tests**

Append to `tests/test_app.py`:

```python
def test_doctor_can_select_registered_patient_and_send_ready_reports(monkeypatch, tmp_path):
    app, doctor, db = _authenticated_app(monkeypatch, tmp_path, "doctor")
    patient = accounts.register_user(
        "Mona Patient", "mona@example.com", "password-2", "patient", db
    )
    app.session_state["transcription"] = {
        "speaker_ids": ["speaker_0", "speaker_1"],
        "turns": [
            {"speaker_id": "speaker_0", "text": "Hello", "start": 0.0, "end": 1.0},
            {"speaker_id": "speaker_1", "text": "Headache", "start": 1.1, "end": 2.0},
        ],
        "language_code": "eng",
        "language_probability": 0.99,
    }
    app.session_state["reports"] = {
        "doctor_report": {"consultation_summary": "Headache discussed."},
        "patient_report": {"what_was_discussed": "Your headache."},
    }
    app.session_state["report_mapping"] = {
        "speaker_0": "Doctor", "speaker_1": "Patient"
    }
    app.session_state["doctor_pdf_report"] = b"%PDF-doctor"
    app.session_state["doctor_pdf_path"] = "data/reports/doctor.pdf"
    app.session_state["patient_pdf_report"] = b"%PDF-patient"
    app.session_state["patient_pdf_path"] = "data/reports/patient.pdf"
    app.session_state["delivery_token"] = "delivery-1"
    app.session_state["audio_path"] = "data/audio/visit.wav"
    app.run(timeout=20)

    patient_selector = next(box for box in app.selectbox if box.label == "Send report to patient")
    patient_selector.set_value(patient.id).run(timeout=20)
    next(button for button in app.button if button.label == "Send to patient").click().run(timeout=20)

    history = accounts.list_doctor_consultations(doctor.id, db)
    assert len(history) == 1
    assert history[0]["patient_email"] == "mona@example.com"


def test_doctor_history_survives_missing_pdf_files(monkeypatch, tmp_path):
    app, doctor, db = _authenticated_app(monkeypatch, tmp_path, "doctor")
    patient = accounts.register_user("Mona", "mona@example.com", "password-2", "patient", db)
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
```

- [ ] **Step 2: Run Doctor dashboard tests and verify failures**

Run: `python -m pytest tests/test_app.py -q`

Expected: patient selector, send action, and Doctor History assertions fail.

- [ ] **Step 3: Implement Doctor dashboard tabs and sending**

Import `uuid4` and the consultation APIs. Create a Doctor dashboard with `New Consultation` and `Report history` tabs. At the start of the New Consultation tab:

```python
patients = list_patients()
patient_options = {patient.id: f"{patient.full_name} · {patient.email}" for patient in patients}
selected_patient_id = st.selectbox(
    "Send report to patient",
    options=list(patient_options),
    format_func=patient_options.get,
    index=None,
    placeholder="Choose a registered patient",
)
```

When reports are successfully generated, set:

```python
st.session_state.delivery_token = uuid4().hex
st.session_state.sent_consultation_id = None
```

Add one shared history-label helper so consultations retain their own language independently of the current Doctor screen:

```python
def localized_sections(
    sections: list[tuple[str, str, str]], language: str
) -> list[tuple[str, str, str]]:
    labels = ARABIC_SECTION_LABELS if language == "Arabic" else {}
    return [(key, labels.get(key, label), icon) for key, label, icon in sections]
```

Below the report tabs, enable Send to Patient only when a patient is selected and all report/PDF paths exist. Call:

```python
consultation_id = send_consultation(
    doctor_id=current_user["id"],
    patient_id=selected_patient_id,
    delivery_token=st.session_state.delivery_token,
    language=language_choice,
    transcript=role_transcript,
    doctor_report=st.session_state.reports["doctor_report"],
    patient_report=st.session_state.reports["patient_report"],
    doctor_pdf_path=st.session_state.doctor_pdf_path,
    patient_pdf_path=st.session_state.patient_pdf_path,
    audio_path=st.session_state.audio_path,
)
st.session_state.sent_consultation_id = consultation_id
```

Disable the button and show a success message after sending. Render Doctor History newest first with expanders. Reuse `render_report()` for both reports. Read each PDF path only when it exists; otherwise render the exact friendly text `PDF file is no longer available.`.

Wrap patient lookup, send, and history queries in `AccountError`/`sqlite3.Error` handling. Show safe application messages only; never include SQL text or the raw exception.

- [ ] **Step 4: Run Doctor UI and account tests**

Run: `python -m pytest tests/test_app.py tests/test_accounts.py -q`

Expected: Doctor selection, idempotent sending, history, missing-file behavior, and account tests pass.

- [ ] **Step 5: Commit Task 4**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: send consultations and show doctor history"
```

### Task 5: Patient Report History

**Files:**
- Modify: `app.py`
- Modify: `tests/test_app.py`

**Interfaces:**
- Consumes: `list_patient_consultations(patient_id)`, `PATIENT_SECTIONS`, and optional Patient PDF paths.
- Produces: a Patient dashboard containing only patient-safe reports and downloads.

- [ ] **Step 1: Add failing Patient history tests**

Append to `tests/test_app.py`:

```python
def test_patient_sees_only_own_patient_report(monkeypatch, tmp_path):
    app, patient, db = _authenticated_app(monkeypatch, tmp_path, "patient")
    doctor = accounts.register_user("Dr. Sara", "doctor2@example.com", "password-2", "doctor", db)
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


def test_patient_empty_state_does_not_show_other_patients_reports(monkeypatch, tmp_path):
    app, patient, db = _authenticated_app(monkeypatch, tmp_path, "patient")
    doctor = accounts.register_user("Dr. Sara", "doctor2@example.com", "password-2", "doctor", db)
    other_patient = accounts.register_user("Other", "other@example.com", "password-3", "patient", db)
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
```

- [ ] **Step 2: Run Patient dashboard tests and verify failures**

Run: `python -m pytest tests/test_app.py -q`

Expected: Patient history content and missing-file assertions fail while database ownership tests remain green.

- [ ] **Step 3: Implement patient-safe history rendering**

Replace the Patient dashboard placeholder with `list_patient_consultations(current_user["id"])`. Render newest-first expanders labelled with doctor name and sent date. Inside each expander:

```python
render_report(
    item["patient_report"],
    localized_sections(PATIENT_SECTIONS, item["language"]),
    "patient",
)
patient_pdf = Path(item["patient_pdf_path"])
if patient_pdf.is_file():
    st.download_button(
        "Download patient PDF report",
        data=patient_pdf.read_bytes(),
        file_name=f"patient-report-{item['id']}.pdf",
        mime="application/pdf",
        key=f"patient-history-pdf-{item['id']}",
    )
else:
    st.caption("PDF file is no longer available.")
```

Use Arabic labels and download text when `item["language"] == "Arabic"`. Do not render transcript text or any Doctor report field in the Patient dashboard; the existing Patient PDF still contains its transcript.

- [ ] **Step 4: Run app and account tests**

Run: `python -m pytest tests/test_app.py tests/test_accounts.py -q`

Expected: all Patient visibility, cross-account isolation, Doctor history, and authentication tests pass.

- [ ] **Step 5: Commit Task 5**

```powershell
git add app.py tests/test_app.py
git commit -m "feat: add patient report history"
```

### Task 6: Demo Deployment Documentation and Full Verification

**Files:**
- Modify: `.gitignore`
- Modify: `README.md`
- Test: complete `tests/` suite

**Interfaces:**
- Consumes: finished account and consultation features.
- Produces: a reproducible local run and Streamlit Community Cloud demonstration checklist.

- [ ] **Step 1: Ignore runtime database files**

Add to `.gitignore`:

```gitignore
data/medical_app.db
data/medical_app.db-journal
data/medical_app.db-shm
data/medical_app.db-wal
```

- [ ] **Step 2: Document the account demonstration flow**

Update `README.md` with:

```markdown
## Demo accounts and report delivery

1. Create one Patient account and one Doctor account from separate browser sessions.
2. Log in as the Doctor and select the registered Patient email.
3. Process a consultation, review both reports, and select **Send to patient**.
4. Confirm both reports appear in Doctor History.
5. Log in as the Patient and confirm only the Patient Report appears.

On Streamlit Community Cloud, add `ELEVENLABS_API_KEY` and
`OPENROUTER_API_KEY` in the app's Secrets settings. SQLite and generated
reports are stored on the running app instance and may disappear after a
restart or redeployment. Register demonstration accounts shortly before
the presentation and avoid redeploying during it.
```

- [ ] **Step 3: Run the complete automated suite**

Run: `python -m pytest -q`

Expected: every account, Streamlit, transcription, report, PDF, storage, and language test passes with zero failures.

- [ ] **Step 4: Compile all application modules**

Run: `python -m py_compile app.py accounts.py services.py storage.py`

Expected: exit code 0 and no output.

- [ ] **Step 5: Perform two-session acceptance verification**

Start the app with `python -m streamlit run app.py`. In two separate private browser windows:

1. Register a Patient account in window A.
2. Register a Doctor account in window B.
3. Log in as the Doctor, select the Patient email, and process a short valid recording.
4. Generate reports and send the consultation.
5. Confirm Doctor History displays Doctor Report, Patient Report, Doctor PDF, and Patient PDF.
6. Log in as the Patient and confirm Patient History displays only Patient Report and Patient PDF.
7. Log out in each window and confirm protected content disappears.

Expected: the complete cross-session demonstration succeeds without raw exceptions or cross-account data exposure.

- [ ] **Step 6: Commit Task 6**

```powershell
git add .gitignore README.md
git commit -m "docs: explain account demo deployment"
```

- [ ] **Step 7: Review the completed branch**

Run:

```powershell
git status --short
git log --oneline -8
```

Expected: only intentional runtime artifacts ignored by Git, six focused implementation commits after the design/plan commits, and no uncommitted source changes.
