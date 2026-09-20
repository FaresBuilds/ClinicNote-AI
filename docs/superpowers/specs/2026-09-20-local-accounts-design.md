# Local Doctor and Patient Accounts Design

## Purpose

Add simple real accounts to the Streamlit graduation demo. Doctors and patients self-register with an email and password. Doctors create consultations, keep both generated reports, and send the patient-facing report to a registered patient. Patients can log in and view the reports previously sent to their account.

This remains a short-lived educational demonstration, not a production healthcare system. It is intended to run on Streamlit Community Cloud for a few hours. Losing accounts and reports after an app restart or redeployment is acceptable.

## Scope

The account system includes:

- Self-registration for Doctor and Patient roles.
- Login and logout.
- Password hashing; plaintext passwords are never stored.
- A doctor-only consultation workflow.
- Selection of a registered patient by email.
- An explicit send action after reports have been generated and reviewed.
- Doctor history containing both Doctor and Patient reports.
- Patient history containing only the Patient Report sent to that patient.
- Separate Doctor and Patient PDF downloads.
- English and Arabic compatibility.

The account system does not include:

- Email verification.
- Password reset.
- Doctor approval or administrator accounts.
- Persistent cloud storage guarantees.
- Notifications outside the application.
- Production healthcare privacy, auditing, or compliance controls.

## Architecture

Keep the existing Streamlit application and service files. Add one small `accounts.py` module responsible for SQLite setup, authentication, and consultation-history queries. Use Python's standard `sqlite3`, `hashlib`, `secrets`, and `hmac` modules; do not add an ORM or external authentication service.

The local database is stored at `data/medical_app.db`. Audio, transcripts, text reports, and PDF reports continue to be stored in their existing `data/` directories. The database stores references to generated artifact paths together with report content.

Streamlit session state holds only the currently authenticated user's identity and transient consultation state. Persistent account and consultation records live in SQLite.

## Data Model

### Users

`users` contains:

- `id`: integer primary key.
- `full_name`: required display name.
- `email`: normalized lowercase email, required and unique.
- `password_hash`: PBKDF2-HMAC-SHA256 password hash.
- `password_salt`: unique random salt.
- `role`: either `doctor` or `patient`.
- `created_at`: UTC timestamp.

Passwords require at least eight characters. Authentication uses constant-time hash comparison.

### Consultations

`consultations` contains:

- `id`: integer primary key.
- `doctor_id`: required reference to a Doctor account.
- `patient_id`: required reference to a Patient account.
- `language`: English or Arabic.
- `transcript`: the role-labelled transcript.
- `doctor_report_json`: complete structured Doctor Report.
- `patient_report_json`: complete structured Patient Report.
- `doctor_pdf_path`: saved Doctor PDF path.
- `patient_pdf_path`: saved Patient PDF path.
- `audio_path`: saved recording path when available.
- `created_at`: UTC timestamp.
- `sent_at`: UTC timestamp set when the doctor sends the consultation.

A consultation becomes visible in histories only after the explicit send action succeeds.

## Authentication and Authorization

Unauthenticated visitors see Login and Create Account tabs. Registration collects full name, email, password, password confirmation, and role. Duplicate emails, invalid email input, mismatched passwords, and short passwords produce friendly validation messages.

After login, session state stores a small user record containing ID, full name, email, and role. Logout clears authentication and all transient consultation data.

Authorization is enforced in database functions, not only by hiding UI elements:

- Only Doctor accounts can create and send consultations.
- A doctor can view consultations only when `doctor_id` matches their own account ID.
- A patient can view consultations only when `patient_id` matches their own account ID.
- Patient queries never return the Doctor Report or Doctor PDF path.

## User Experience

### Entry Screen

The existing medical visual style is retained. A compact account card presents Login and Create Account tabs. Successful registration directs the user to log in.

### Doctor Dashboard

The Doctor dashboard includes:

1. A header showing the doctor's name and a logout button.
2. A New Consultation area containing the existing language, audio, transcription, role assignment, report generation, and download workflow.
3. A registered-patient selector showing patient name and email.
4. A Send to Patient button enabled only when both reports and both PDFs are ready.
5. A consultation history showing date, patient, language, both reports, and both PDF downloads.

Sending inserts one consultation row. The doctor receives a success message and the consultation immediately appears in Doctor History.

### Patient Dashboard

The Patient dashboard includes:

1. A header showing the patient's name and a logout button.
2. A report history ordered newest first.
3. For each consultation: date, doctor name, language, Patient Report sections, and Patient PDF download.

The Patient PDF continues to include the consultation transcript and the Patient Report. Patients never receive or view the Doctor Report.

## Error Handling

Show friendly Streamlit messages for:

- Invalid registration fields.
- Duplicate email addresses.
- Incorrect login credentials.
- Missing or deleted patient accounts.
- Attempted role violations.
- Database initialization or write failures.
- Missing saved PDF files.
- Sending before report generation is complete.

Do not display raw SQL, password data, API responses, or stack traces.

## Deployment Behavior

The SQLite database and report files are created on the Streamlit Community Cloud app instance. Different browsers and computers using the same running app share the same accounts and consultations.

Streamlit Community Cloud does not guarantee persistence of local files. A restart, sleep recovery, or redeployment may erase demo accounts and reports. This is accepted for the short graduation demonstration. Demonstration accounts should be registered shortly before presenting, and the app should not be redeployed during the presentation.

API keys remain in Streamlit Secrets or environment variables and are never stored in SQLite or exposed to browsers.

## Testing

Focused automated tests cover:

- Database initialization.
- Doctor and Patient registration.
- Email normalization and duplicate rejection.
- Password hashing and successful/failed login.
- Doctor-only consultation creation.
- Patient lookup by email.
- Doctor history containing both reports.
- Patient history excluding Doctor Report data.
- Prevention of cross-account consultation access.
- Streamlit login, registration, role routing, and logout behavior.

The existing transcription, reporting, PDF, storage, and language tests remain in the full regression suite.

## Success Criteria

The feature is complete when two users can self-register on the deployed Streamlit app, log in from separate browser sessions, and demonstrate this flow:

1. A doctor selects the patient account.
2. The doctor processes a consultation and reviews both generated reports.
3. The doctor sends the consultation.
4. The doctor sees both reports in Doctor History.
5. The patient logs in and sees only the Patient Report and Patient PDF in Patient History.
