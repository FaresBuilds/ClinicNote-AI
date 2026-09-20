# Firebase Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace SQLite and local consultation artifacts with Firebase Authentication and Cloud Firestore while rebuilding historical PDFs from stored transcript/report data.

**Architecture:** Keep `accounts.py` as the single account/persistence boundary, but replace its SQLite implementation with lazy Firebase initialization, Firebase Auth REST calls, and Firestore documents. `app.py` sends audio bytes directly to ElevenLabs, stores consultation content only when a doctor sends it, and generates current or historical PDF bytes in memory.

**Tech Stack:** Python 3.10+, Streamlit 1.51+, Requests 2.32+, Firebase Admin Python SDK 7.6+, Cloud Firestore, pytest, ReportLab

**Spec:** `docs/superpowers/specs/2026-09-21-firebase-persistence-design.md`

## Global Constraints

- Use Firebase Authentication email/password and Cloud Firestore only; do not use Firebase Storage, Hosting, or Cloud Functions.
- Load `FIREBASE_WEB_API_KEY`, `FIREBASE_PROJECT_ID`, and `FIREBASE_SERVICE_ACCOUNT_B64` from environment variables or root-level Streamlit secrets without logging their values.
- Do not migrate existing SQLite accounts or consultations.
- Store no passwords, audio bytes, PDF bytes, or local file paths in Firestore.
- A doctor retains both reports; a patient retrieves only their own patient report and shared transcript.
- Preserve English and Arabic data and PDF generation.
- Reject consultation records over 900,000 serialized UTF-8 bytes before writing.

## Review Focus

- Malformed or mismatched service-account configuration must become a safe setup error; Task 1 tests it.
- Firebase Auth may return `EMAIL_EXISTS` or `INVALID_LOGIN_CREDENTIALS`; Task 2 tests both mappings.
- Repeating a delivery token for the same recipient must be idempotent, while reusing it for another recipient must fail; Task 2 tests both paths.
- Patient history must omit `doctor_report`; Task 2 asserts the returned dictionary does not contain it.
- Historical Arabic data must create a downloadable PDF without any local PDF path; Task 2 exercises that complete UI path.

---

### Task 1: Add and validate Firebase configuration without changing live persistence

**Files:**
- Modify: `requirements.txt`
- Modify: `accounts.py`
- Modify: `tests/test_accounts.py`

**Interfaces:**
- Produces: `FirebaseConfig`, `_load_firebase_config() -> FirebaseConfig`, `_firebase_db() -> firestore.Client`, `_server_timestamp() -> Any`, and `initialize_firebase() -> None`.
- Preserves: all existing SQLite public functions until Task 2, keeping the full suite green.

- [ ] **Step 1: Write failing configuration tests**

Add helpers and tests that never print credentials:

```python
def _firebase_environment(monkeypatch, env_project="medical-demo", credential_project="medical-demo"):
    info = {
        "type": "service_account",
        "project_id": credential_project,
        "private_key": "-----BEGIN PRIVATE KEY-----\nkey\n-----END PRIVATE KEY-----\n",
        "client_email": "firebase-adminsdk@medical-demo.iam.gserviceaccount.com",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
    monkeypatch.setenv("FIREBASE_WEB_API_KEY", "AIza-test")
    monkeypatch.setenv("FIREBASE_PROJECT_ID", env_project)
    monkeypatch.setenv(
        "FIREBASE_SERVICE_ACCOUNT_B64",
        base64.b64encode(json.dumps(info).encode()).decode(),
    )


def test_load_firebase_config_decodes_matching_service_account(monkeypatch):
    _firebase_environment(monkeypatch)
    config = accounts._load_firebase_config()
    assert config.web_api_key == "AIza-test"
    assert config.project_id == "medical-demo"
    assert config.service_account["project_id"] == "medical-demo"


def test_load_firebase_config_rejects_project_mismatch(monkeypatch):
    _firebase_environment(monkeypatch, env_project="wrong-project")
    with pytest.raises(accounts.AccountError, match="does not match"):
        accounts._load_firebase_config()
```

Also test missing settings, invalid Base64, invalid JSON, missing required service-account fields, and invalid private-key markers.

- [ ] **Step 2: Run the focused tests and confirm the intended failure**

Run: `pytest tests/test_accounts.py -k "firebase_config" -v`

Expected: FAIL because `FirebaseConfig` and `_load_firebase_config` do not exist.

- [ ] **Step 3: Add the dependency and minimal lazy initializer**

Add `firebase-admin>=7.6,<8` to `requirements.txt`, run `python -m pip install -r requirements.txt`, and implement:

```python
@dataclass(frozen=True)
class FirebaseConfig:
    web_api_key: str
    project_id: str
    service_account: dict[str, Any]


def _setting(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    try:
        return str(st.secrets.get(name, "")).strip()
    except Exception:
        return ""
```

`_load_firebase_config` validates all three values, decodes Base64 and JSON, checks `type`, `project_id`, `private_key`, `client_email`, and `token_uri`, verifies project IDs match, and raises one safe `AccountError` message for invalid configuration. `_firebase_db` initializes a named Firebase Admin app once with `credentials.Certificate`, and `initialize_firebase` triggers this lazy initialization without reading or writing application data. `_server_timestamp` returns `firestore.SERVER_TIMESTAMP` for deterministic replacement in tests.

- [ ] **Step 4: Prove Task 1 is green**

Run: `pytest tests/test_accounts.py -k "firebase_config" -v`

Run: `pytest -q`

Expected: every test passes because SQLite behavior remains untouched during this additive task.

- [ ] **Step 5: Commit Task 1**

```bash
git add requirements.txt accounts.py tests/test_accounts.py
git commit -m "feat: initialize firebase persistence"
```

### Task 2: Atomically replace SQLite accounts, consultation storage, and local report paths

**Files:**
- Replace: `accounts.py`
- Modify: `app.py`
- Replace: `tests/test_accounts.py`
- Modify: `tests/test_app.py`
- Create: `tests/firebase_fakes.py`

**Interfaces:**
- Produces: `User(id: str, full_name: str, email: str, role: str, id_token: str = "", refresh_token: str = "")`.
- Produces: `register_user(full_name, email, password, role) -> User`, `authenticate_user(email, password) -> User | None`, and `list_patients() -> list[User]`.
- Produces: `send_consultation(*, doctor_id: str, patient_id: str, delivery_token: str, language: str, transcript: str, transcript_turns: list[dict[str, Any]], doctor_report: dict[str, Any], patient_report: dict[str, Any]) -> str`.
- Produces: `list_doctor_consultations(doctor_id: str) -> list[dict[str, Any]]` and `list_patient_consultations(patient_id: str) -> list[dict[str, Any]]`.
- Consumes: `build_role_report_pdf(...) -> bytes` for in-memory current and historical downloads.

- [ ] **Step 1: Create deterministic Firebase fakes and rewrite account tests first**

`tests/firebase_fakes.py` provides `FakeSnapshot`, `FakeDocument`, `FakeCollection`, and `FakeFirestore` with `document().get()/set()` and `collection().stream()`. It also provides `FakeAuth.request(operation, payload)` supporting `signUp`, `signInWithPassword`, configured error codes, and deletion. `install_firebase_fakes(monkeypatch)` patches `_firebase_db`, `_auth_request`, `_delete_auth_user`, and `_server_timestamp`.

The fake data surfaces are ordinary dictionaries:

```python
class FakeFirestore:
    def __init__(self):
        self.collections = {"users": FakeCollection(), "consultations": FakeCollection()}

    def collection(self, name):
        return self.collections[name]

    @property
    def users(self):
        return self.collections["users"].documents

    @property
    def consultations(self):
        return self.collections["consultations"].documents


def install_firebase_fakes(monkeypatch):
    fakes = FirebaseFakes(db=FakeFirestore(), auth=FakeAuth())
    monkeypatch.setattr(accounts, "_firebase_db", lambda: fakes.db)
    monkeypatch.setattr(accounts, "_auth_request", fakes.auth.request)
    monkeypatch.setattr(accounts, "_delete_auth_user", fakes.auth.delete)
    monkeypatch.setattr(accounts, "_server_timestamp", lambda: FIXED_TIME)
    return fakes
```

Replace SQLite account tests with Firebase-focused tests for input validation, normalization, registration/profile creation, passwords omitted from Firestore, duplicate email, invalid login, safe network errors, patient listing, best-effort Auth rollback after a profile-write failure, role authorization, content-size validation, idempotent delivery, history ordering, and patient isolation.

Core assertions include:

```python
user = accounts.register_user(" Dr. Sara ", "SARA@EXAMPLE.COM", "password-1", "doctor")
assert user.id == "sara-uid"
assert firebase_fakes.db.users[user.id] == {
    "full_name": "Dr. Sara",
    "email": "sara@example.com",
    "role": "doctor",
    "created_at": FIXED_TIME,
}

firebase_fakes.auth.fail_with("INVALID_LOGIN_CREDENTIALS")
assert accounts.authenticate_user("missing@example.com", "password-1") is None
```

For consultations, register one doctor and two patients, send one record to each patient, and assert doctor history has both reports while each patient sees only their own record, `patient_report`, transcript fields, and doctor display metadata. Assert `doctor_report` is absent from patient results.

- [ ] **Step 2: Rewrite app tests for Firebase-shaped records and path-free PDFs before production changes**

Use `install_firebase_fakes` before each `AppTest` import. Put ready reports in session with a fixed delivery token and PDF byte values, but no audio or PDF paths. Add tests proving:

```python
send_button = next(button for button in app.button if button.label == "Send to patient")
assert not send_button.disabled
send_button.click().run(timeout=20)
saved = firebase_fakes.db.consultations["delivery-token"]
assert saved["transcript_turns"][0]["role"] == "Doctor"
assert "doctor_pdf_path" not in saved
assert "patient_pdf_path" not in saved
```

Create an Arabic history record through `send_consultation`, run the patient dashboard, locate the PDF download button, and assert its bytes start with `%PDF`. Retain route, language, role visibility, empty-history isolation, and both doctor/patient report tests.

- [ ] **Step 3: Run the rewritten tests and confirm the intended red state**

Run: `pytest tests/test_accounts.py tests/test_app.py -v`

Expected: FAIL because production still accepts database/PDF paths and uses SQLite.

- [ ] **Step 4: Replace `accounts.py` with the minimal Firebase implementation**

Keep `AccountError`, `DuplicateEmailError`, and `AuthorizationError`. Add internal `FirebaseAuthError(code)` so `_auth_request` can parse Firebase's JSON error safely without exposing raw bodies.

Registration calls:

```python
signup = _auth_request("signUp", {
    "email": normalized_email,
    "password": password,
    "returnSecureToken": True,
})
```

It writes only `full_name`, `email`, `role`, and `_server_timestamp()` to `users/{localId}`. If that write fails, `_delete_auth_user(localId)` is attempted before raising `AccountError`. Login calls `signInWithPassword`, maps `EMAIL_NOT_FOUND`, `INVALID_PASSWORD`, and `INVALID_LOGIN_CREDENTIALS` to `None`, loads the matching user profile, and keeps ID/refresh tokens only in the returned server-side session object.

Use `consultations/{delivery_token}` as the deterministic document ID. Validate both user roles, language, transcript, turns, and reports; denormalize doctor/patient names and emails; attach `_server_timestamp()`; reject serialized records above 900,000 bytes; and write once. A same-target retry returns the existing ID, while a different-target reuse raises `AuthorizationError`.

History streams the small demo collection, filters by the relevant UID, sorts by normalized `sent_at` descending in Python, and shapes results. Patient-shaped results intentionally omit `doctor_report`, doctor-only metadata, and authentication tokens.

- [ ] **Step 5: Remove local persistence and rebuild historical PDFs in `app.py`**

Remove `sqlite3`, `Path`, `DATA_ROOT`, local directory constants, SQLite initialization, `save_bytes`, `save_text`, `save_pdf`, and `audio_path`/PDF-path session keys. Call `initialize_firebase()` at startup and show a service-neutral `AccountError` message if configuration is unavailable.

Transcription sends selected bytes directly to ElevenLabs. Report generation retains only `doctor_pdf_report` and `patient_pdf_report` bytes in the current session. Sending becomes ready when a patient is selected, reports match the current speaker mapping, and a delivery token exists:

```python
consultation_id = send_consultation(
    doctor_id=current_user["id"],
    patient_id=selected_patient_id,
    delivery_token=st.session_state.delivery_token,
    language=language_choice,
    transcript=role_transcript,
    transcript_turns=labelled_turns,
    doctor_report=reports["doctor_report"],
    patient_report=reports["patient_report"],
)
```

Replace `render_saved_pdf` with `render_history_pdf(item, audience)`. It selects the correct report and localized section list, calls `build_role_report_pdf` with `item["transcript_turns"]` and stored language, then passes returned bytes directly to `st.download_button`. If PDF generation fails, display a friendly message while leaving the report cards visible.

- [ ] **Step 6: Prove the atomic cutover is green**

Run: `pytest tests/test_accounts.py tests/test_app.py -v`

Run: `pytest -q`

Expected: every test passes without SQLite, local-path, unhandled exception, or warning output.

- [ ] **Step 7: Commit Task 2**

```bash
git add accounts.py app.py tests/firebase_fakes.py tests/test_accounts.py tests/test_app.py
git commit -m "feat: store accounts and consultations in firebase"
```

### Task 3: Deployment documentation and live verification

**Files:**
- Modify: `README.md`
- Create: `.env.example`

**Interfaces:**
- Documents the exact settings accepted locally and by Streamlit Community Cloud.
- Adds no new application subsystem.

- [ ] **Step 1: Add the safe template and Firebase deployment instructions**

Create `.env.example`:

```dotenv
ELEVENLABS_API_KEY=
OPENROUTER_API_KEY=
OPENROUTER_MODEL=google/gemini-3.8-flash
FIREBASE_WEB_API_KEY=
FIREBASE_PROJECT_ID=
FIREBASE_SERVICE_ACCOUNT_B64=
```

Update README setup, Firebase Authentication/Firestore requirements, Streamlit Secrets syntax, PDF regeneration behavior, and removal of SQLite/local persistence warnings.

- [ ] **Step 2: Run static and automated verification**

Run: `python -m compileall app.py accounts.py services.py storage.py`

Run: `pytest -q`

Expected: compilation succeeds and every test passes.

- [ ] **Step 3: Perform live read-only Firebase verification without printing identifiers or credentials**

Load `.env`, initialize the Admin SDK, and stream at most one document from `users`. Then send a Firebase Auth `signInWithPassword` request using a guaranteed-invalid `.invalid` email. Treat only the expected invalid-credential response as proof that the Web API key and email/password provider are reachable. Print status labels only:

```text
Firebase Admin credential: OK
Cloud Firestore read: OK
Firebase email/password endpoint: OK
```

- [ ] **Step 4: Verify Streamlit startup**

Start `streamlit run app.py --server.headless true --server.port 8501`, request `http://localhost:8501/_stcore/health`, confirm HTTP 200 with `ok`, and terminate only the spawned Streamlit process.

- [ ] **Step 5: Review and commit**

Run: `git diff --check`

Run: `git status --short`

Expected: no whitespace errors and only intentional files changed.

```bash
git add README.md .env.example
git commit -m "docs: explain firebase deployment"
```
