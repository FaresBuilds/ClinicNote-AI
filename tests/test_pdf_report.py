from io import BytesIO

from pypdf import PdfReader

import storage


DOCTOR_SECTIONS = [
    ("patient_complaints", "Patient complaints", ""),
    ("consultation_summary", "Consultation summary", ""),
]
PATIENT_SECTIONS = [
    ("what_was_discussed", "What was discussed", ""),
    ("things_to_remember", "Things to remember", ""),
]


def test_doctor_pdf_contains_transcript_and_only_doctor_report():
    pdf = storage.build_role_report_pdf(
        turns=[
            {"role": "Doctor", "text": "How are you feeling?", "start": 0.0, "end": 2.0},
            {"role": "Patient", "text": "I have a headache.", "start": 2.1, "end": 4.0},
        ],
        report={
            "patient_complaints": ["Headache"],
            "consultation_summary": "Headache was discussed.",
        },
        sections=DOCTOR_SECTIONS,
        audience="doctor",
        language="English",
    )

    assert pdf.startswith(b"%PDF")
    reader = PdfReader(BytesIO(pdf))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert len(reader.pages) >= 2
    assert "CONSULTATION TRANSCRIPT" in extracted
    assert "How are you feeling?" in extracted
    assert "DOCTOR REPORT" in extracted
    assert "Headache was discussed." in extracted
    assert "PATIENT REPORT" not in extracted


def test_patient_pdf_contains_transcript_and_only_patient_report():
    pdf = storage.build_role_report_pdf(
        turns=[
            {"role": "Doctor", "text": "Please rest.", "start": 0.0, "end": 2.0},
            {"role": "Patient", "text": "I understand.", "start": 2.1, "end": 4.0},
        ],
        report={
            "what_was_discussed": "Your headache.",
            "things_to_remember": ["Return if symptoms worsen."],
        },
        sections=PATIENT_SECTIONS,
        audience="patient",
        language="English",
    )

    reader = PdfReader(BytesIO(pdf))
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "CONSULTATION TRANSCRIPT" in extracted
    assert "PATIENT REPORT" in extracted
    assert "Return if symptoms worsen." in extracted
    assert "DOCTOR REPORT" not in extracted


def test_patient_pdf_supports_arabic_and_saves_locally(tmp_path):
    pdf = storage.build_role_report_pdf(
        turns=[
            {"role": "Doctor", "text": "كيف تشعر اليوم؟", "start": 0.0, "end": 1.5},
            {"role": "Patient", "text": "أشعر بصداع.", "start": 1.6, "end": 3.0},
        ],
        report={
            "what_was_discussed": "تمت مناقشة الصداع.",
            "things_to_remember": ["العودة إذا ساءت الأعراض."],
        },
        sections=[
            ("what_was_discussed", "ما تمت مناقشته", ""),
            ("things_to_remember", "أمور يجب تذكرها", ""),
        ],
        audience="patient",
        language="Arabic",
    )

    saved = storage.save_pdf(tmp_path, pdf, "patient-consultation-report")

    assert saved.parent == tmp_path
    assert saved.suffix == ".pdf"
    assert saved.read_bytes() == pdf
    reader = PdfReader(saved)
    assert len(reader.pages) >= 2
    extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "00:00 - 00:01" in extracted
