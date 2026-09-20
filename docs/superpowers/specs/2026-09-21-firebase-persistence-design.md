# Firebase Persistence Design

## Intent

Replace the demo's local SQLite accounts and consultation history with Firebase so the application works on Streamlit Community Cloud and data survives app restarts. Keep the application small, preserve the existing doctor/patient workflow, and use only free-tier Firebase Authentication and Cloud Firestore. Do not use Firebase Storage.

Success means doctors and patients can self-register and sign in with email/password, doctors can send completed consultations to registered patients, both roles see only the history intended for them, and historical PDFs are rebuilt from Firestore data whenever requested.

## Architecture

The Streamlit Python process remains the only application server. Firebase Authentication owns email/password credentials. Registration and sign-in use the Firebase Authentication REST API with `FIREBASE_WEB_API_KEY`. The Firebase Admin Python SDK uses the Base64-encoded service-account credential to read and write Cloud Firestore.

The existing `accounts.py` public interface remains the persistence boundary so `app.py` needs only focused changes. Its implementation changes from SQLite to Firebase. Firestore access uses the Admin SDK, so authorization remains explicit in the Python functions: doctor-only sending, patient target validation, and role-scoped history queries.

Required settings are:

- `FIREBASE_WEB_API_KEY`
- `FIREBASE_PROJECT_ID`
- `FIREBASE_SERVICE_ACCOUNT_B64`
- Existing `ELEVENLABS_API_KEY`, `OPENROUTER_API_KEY`, and optional `OPENROUTER_MODEL`

Configuration loads from local environment variables and Streamlit secrets. Credential values are never logged or shown in the interface.

## Firestore Data Model

`users/{uid}` stores:

- `full_name`
- `email`
- `role`, either `doctor` or `patient`
- `created_at`, a server timestamp

`consultations/{consultation_id}` stores only the material needed for history and PDF regeneration:

- `delivery_token`, used to make sending idempotent
- `doctor_id`, `doctor_name`, and `doctor_email`
- `patient_id`, `patient_name`, and `patient_email`
- `language`
- `transcript`
- `transcript_turns`, including role labels and available timestamps
- `doctor_report`
- `patient_report`
- `sent_at`, a server timestamp

No passwords, audio bytes, local paths, or PDF bytes are stored in Firestore. Existing SQLite data is not migrated.

For the graduation demo, one consultation is one Firestore document. Before writing, the application rejects an unexpectedly large record with a friendly error rather than exceeding Firestore's 1 MiB document limit.

## User and Consultation Flows

Registration validates the name, email, password, and role locally, creates the Firebase Authentication user, and then creates the matching Firestore profile. If profile creation fails, the newly created Auth user is deleted when possible so the user can retry cleanly. Duplicate-email and weak-password responses become friendly application messages.

Login sends the credentials to Firebase Authentication, then loads the Firestore profile by the returned Firebase UID. The Streamlit session stores the small user object and authentication tokens needed for the current browser session. Logout clears the consultation state and authenticated session.

When a doctor sends a consultation, the app stores the role-labelled transcript turns and both structured reports. `delivery_token` prevents accidental duplicate sends. Doctor history returns both reports. Patient history returns only the patient-facing report, although the stored consultation retains both for the doctor's view.

## PDF and Local Files

New transcription audio is passed directly to ElevenLabs and is not persistently saved. Transcript text and reports are not persisted to local disk. PDF generation continues to use the existing ReportLab builder:

- Fresh reports use the in-memory transcript and report structures.
- Historical reports rebuild PDF bytes from the Firestore consultation document when the download control is rendered.

This removes dependency on Streamlit's ephemeral filesystem and eliminates missing historical PDF files.

## Errors and Reliability

Firebase configuration errors, unavailable authentication, unavailable Firestore, duplicate email, invalid login, authorization failures, and oversized consultation records are converted to concise `AccountError` messages. Raw Firebase responses, service-account data, and stack traces are not displayed.

Queries use simple equality filters and sort the small demo result sets in Python, avoiding required composite-index setup. All Firestore timestamps are normalized to ISO strings before reaching the UI.

## Testing and Verification

Focused unit tests use small fake Firebase Auth and Firestore adapters; they do not call the live project or consume real user data. Tests cover registration, login, duplicate email, role filtering, authorization, idempotent sends, patient data isolation, and PDF regeneration from stored content.

Verification includes:

1. Full automated test suite.
2. Import/compile check.
3. Live read-only Firebase credential and Firestore connectivity check without printing secrets.
4. Streamlit startup health check.

## Out of Scope

- Firebase Storage, Hosting, Cloud Functions, phone authentication, email verification, password reset, account administration, data migration, and offline synchronization.
- Production healthcare compliance or long-term storage guarantees.
