from __future__ import annotations

import hashlib
import hmac
import json
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
            """
        )


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()


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
                (
                    name,
                    normalized,
                    _hash_password(password, salt),
                    salt.hex(),
                    role,
                    created_at,
                ),
            )
            row = connection.execute(
                "SELECT id, full_name, email, role FROM users WHERE id = ?",
                (cursor.lastrowid,),
            ).fetchone()
    except sqlite3.IntegrityError as exc:
        raise DuplicateEmailError(
            "An account with this email already exists."
        ) from exc
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
            raise AuthorizationError(
                "Only doctors can send reports to patient accounts."
            )
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
                doctor_id,
                patient_id,
                delivery_token,
                language,
                transcript,
                json.dumps(doctor_report, ensure_ascii=False),
                json.dumps(patient_report, ensure_ascii=False),
                doctor_pdf_path,
                patient_pdf_path,
                audio_path,
                now,
                now,
            ),
        )
        row = connection.execute(
            """SELECT id, doctor_id, patient_id FROM consultations
               WHERE delivery_token = ?""",
            (delivery_token,),
        ).fetchone()
        if row["doctor_id"] != doctor_id or row["patient_id"] != patient_id:
            raise AuthorizationError(
                "This consultation was already sent to another account."
            )
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
