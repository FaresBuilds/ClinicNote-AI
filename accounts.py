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
