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
