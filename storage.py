"""Simple local artifact storage for the Streamlit demo."""

from __future__ import annotations

from io import BytesIO
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

import arabic_reshaper
from bidi.algorithm import get_display
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".mp4", ".mpeg", ".mpga", ".webm", ".ogg"}
MAX_AUDIO_BYTES = 500 * 1024 * 1024


class StorageError(ValueError):
    """A safe, user-facing validation or storage error."""


def microphone_access_message(url: str, is_embedded: bool) -> str | None:
    """Explain browser contexts where microphone capture cannot be used reliably."""
    if is_embedded:
        return (
            "Microphone access is usually blocked inside embedded previews. "
            "Open this app directly in Chrome or Edge, then allow microphone access, "
            "or switch to Upload audio."
        )

    parsed = urlparse(url or "")
    local_hosts = {"localhost", "127.0.0.1", "::1"}
    if parsed.scheme != "https" and parsed.hostname not in local_hosts:
        return (
            "Browsers block microphone access on non-secure network addresses. "
            "Open the app with HTTPS or localhost, then allow microphone access, "
            "or switch to Upload audio."
        )
    return None


def validate_audio(name: str, data: bytes) -> str:
    safe_name = Path(name or "recording.wav").name
    if not data:
        raise StorageError("The selected audio file is empty.")
    if len(data) > MAX_AUDIO_BYTES:
        raise StorageError("The audio file is larger than the 500 MB demo limit.")
    if Path(safe_name).suffix.lower() not in ALLOWED_AUDIO_EXTENSIONS:
        raise StorageError("Unsupported audio format. Use WAV, MP3, M4A, MP4, MPEG, MPGA, WEBM, or OGG.")
    return safe_name


def _unique_name(stem: str, suffix: str) -> str:
    clean_stem = re.sub(r"[^A-Za-z0-9_-]+", "-", stem).strip("-") or "consultation"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{clean_stem}-{uuid4().hex[:8]}{suffix}"


def save_bytes(directory: str | Path, data: bytes, original_name: str) -> Path:
    safe_name = validate_audio(original_name, data)
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    source = Path(safe_name)
    target = target_dir / _unique_name(source.stem, source.suffix.lower())
    target.write_bytes(data)
    return target


def save_text(directory: str | Path, text: str, prefix: str) -> Path:
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _unique_name(prefix, ".txt")
    target.write_text(text, encoding="utf-8")
    return target


def save_pdf(directory: str | Path, data: bytes, prefix: str) -> Path:
    """Save generated PDF bytes with a unique local filename."""
    if not data.startswith(b"%PDF"):
        raise StorageError("The generated PDF is invalid. Please generate the reports again.")
    target_dir = Path(directory)
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / _unique_name(prefix, ".pdf")
    target.write_bytes(data)
    return target


def _register_pdf_fonts() -> tuple[str, str]:
    regular_candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
        Path("/Library/Fonts/Arial Unicode.ttf"),
    ]
    bold_candidates = [
        Path("C:/Windows/Fonts/arialbd.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
        Path("/Library/Fonts/Arial Bold.ttf"),
    ]
    regular = next((path for path in regular_candidates if path.exists()), None)
    bold = next((path for path in bold_candidates if path.exists()), regular)
    if regular is None or bold is None:
        raise StorageError("A Unicode font is required to create the PDF report.")
    if "MedicalPDF" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("MedicalPDF", str(regular)))
    if "MedicalPDFBold" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("MedicalPDFBold", str(bold)))
    return "MedicalPDF", "MedicalPDFBold"


def _pdf_text(value: Any, is_arabic: bool) -> str:
    text = str(value or "").strip()
    if is_arabic and text:
        text = get_display(arabic_reshaper.reshape(text), base_dir="R")
    return escape(text).replace("\n", "<br/>")


def _pdf_timestamp(seconds: Any) -> str:
    try:
        total = max(0, int(float(seconds)))
    except (TypeError, ValueError):
        total = 0
    return f"{total // 60:02d}:{total % 60:02d}"


def build_role_report_pdf(
    *,
    turns: list[dict[str, Any]],
    report: dict[str, Any],
    sections: list[tuple[str, str, str]],
    audience: str,
    language: str,
) -> bytes:
    """Create one polished transcript-and-report PDF for a doctor or patient."""
    if audience not in {"doctor", "patient"}:
        raise StorageError("PDF audience must be either doctor or patient.")
    font, bold_font = _register_pdf_fonts()
    is_arabic = language == "Arabic"
    is_doctor = audience == "doctor"
    alignment = TA_RIGHT if is_arabic else TA_LEFT
    navy = colors.HexColor("#102A43")
    blue = colors.HexColor("#2563EB")
    teal = colors.HexColor("#0F766E")
    ink = colors.HexColor("#243B53")
    muted = colors.HexColor("#627D98")
    line = colors.HexColor("#DDE7EF")
    page_width, _ = A4
    content_width = page_width - 34 * mm
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=17 * mm,
        leftMargin=17 * mm,
        topMargin=20 * mm,
        bottomMargin=18 * mm,
        title="Doctor Consultation Report" if is_doctor else "Patient Consultation Report",
        author="Clinical Conversation Companion",
    )
    base = getSampleStyleSheet()
    body = ParagraphStyle(
        "MedicalBody",
        parent=base["BodyText"],
        fontName=font,
        fontSize=9.5,
        leading=14,
        textColor=ink,
        alignment=alignment,
        spaceAfter=3,
    )
    small = ParagraphStyle(
        "MedicalSmall",
        parent=body,
        fontSize=8,
        leading=11,
        textColor=muted,
    )
    small_ltr = ParagraphStyle(
        "MedicalSmallLTR",
        parent=small,
        alignment=TA_RIGHT,
    )
    label = ParagraphStyle(
        "MedicalLabel",
        parent=body,
        fontName=bold_font,
        fontSize=10,
        leading=14,
        textColor=navy,
        spaceAfter=5,
    )
    section_title = ParagraphStyle(
        "MedicalSectionTitle",
        parent=body,
        fontName=bold_font,
        fontSize=18,
        leading=23,
        textColor=navy,
        spaceAfter=10,
    )
    white_title = ParagraphStyle(
        "MedicalWhiteTitle",
        parent=body,
        fontName=bold_font,
        fontSize=22,
        leading=27,
        textColor=colors.white,
    )
    white_subtitle = ParagraphStyle(
        "MedicalWhiteSubtitle",
        parent=body,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#D7EEF0"),
    )

    copy = {
        "title": (
            ("تقرير الطبيب للاستشارة" if is_doctor else "تقرير المريض للاستشارة")
            if is_arabic
            else ("Doctor Consultation Report" if is_doctor else "Patient Consultation Report")
        ),
        "subtitle": (
            ("نص المحادثة والتوثيق السريري" if is_doctor else "نص المحادثة وملخص مبسط للمريض")
            if is_arabic
            else (
                "Consultation transcript and clinician documentation"
                if is_doctor
                else "Consultation transcript and patient-friendly summary"
            )
        ),
        "transcript": "نص الاستشارة" if is_arabic else "CONSULTATION TRANSCRIPT",
        "report": (
            ("تقرير الطبيب" if is_doctor else "تقرير المريض")
            if is_arabic
            else ("DOCTOR REPORT" if is_doctor else "PATIENT REPORT")
        ),
        "language": "اللغة: العربية" if is_arabic else "Language: English",
        "generated": "تاريخ الإنشاء" if is_arabic else "Generated",
        "turns": "عدد المقاطع" if is_arabic else "Conversation turns",
        "doctor_role": "الطبيب" if is_arabic else "Doctor",
        "patient_role": "المريض" if is_arabic else "Patient",
        "fallback": "غير مذكور في المحادثة" if is_arabic else "Not mentioned in the conversation",
        "footer": "Clinical Conversation Companion",
        "page": "صفحة" if is_arabic else "Page",
    }

    def p(text: Any, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(_pdf_text(text, is_arabic), style)

    def page_decor(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setStrokeColor(line)
        canvas.setLineWidth(0.5)
        canvas.line(17 * mm, 13 * mm, page_width - 17 * mm, 13 * mm)
        canvas.setFont(font, 7.5)
        canvas.setFillColor(muted)
        canvas.drawString(17 * mm, 8.5 * mm, copy["footer"])
        page_label = _pdf_text(f'{copy["page"]} {doc.page}', is_arabic)
        canvas.drawRightString(page_width - 17 * mm, 8.5 * mm, page_label)
        canvas.restoreState()

    story: list[Any] = []
    hero = Table(
        [[p(copy["title"], white_title)], [p(copy["subtitle"], white_subtitle)]],
        colWidths=[content_width],
    )
    hero.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), navy),
                ("BOX", (0, 0), (-1, -1), 0.8, teal),
                ("LEFTPADDING", (0, 0), (-1, -1), 15),
                ("RIGHTPADDING", (0, 0), (-1, -1), 15),
                ("TOPPADDING", (0, 0), (-1, 0), 15),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 4),
                ("TOPPADDING", (0, 1), (-1, 1), 0),
                ("BOTTOMPADDING", (0, 1), (-1, 1), 15),
            ]
        )
    )
    story.extend([hero, Spacer(1, 7 * mm)])
    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    generated_cell = (
        [p(copy["generated"], label), Paragraph(escape(generated_at), small_ltr)]
        if is_arabic
        else [p(f'{copy["generated"]}: {generated_at}', small)]
    )
    metadata = Table(
        [[p(copy["language"], label), p(f'{copy["turns"]}: {len(turns)}', label), generated_cell]],
        colWidths=[content_width * 0.25, content_width * 0.25, content_width * 0.5],
    )
    metadata.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#EDF5F8")),
                ("BOX", (0, 0), (-1, -1), 0.6, line),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 9),
                ("RIGHTPADDING", (0, 0), (-1, -1), 9),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([metadata, Spacer(1, 4 * mm)])
    story.append(p(copy["transcript"], section_title))

    for turn in turns:
        role = str(turn.get("role") or "Speaker")
        shown_role = copy["patient_role"] if role == "Patient" else copy["doctor_role"]
        timestamp = f"{_pdf_timestamp(turn.get('start'))} - {_pdf_timestamp(turn.get('end'))}"
        role_color = teal if role == "Patient" else blue
        background = colors.HexColor("#ECFEFF") if role == "Patient" else colors.HexColor("#EFF6FF")
        role_style = ParagraphStyle(
            f"Role{role}", parent=label, textColor=role_color, fontSize=9, spaceAfter=0
        )
        head = Table(
            [[p(shown_role, role_style), Paragraph(escape(timestamp), small_ltr)]],
            colWidths=[content_width * 0.68, content_width * 0.32],
        )
        head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
        card = Table(
            [[head], [p(turn.get("text") or copy["fallback"]) ]],
            colWidths=[content_width],
        )
        card.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, -1), background),
                    ("BOX", (0, 0), (-1, -1), 0.7, line),
                    ("LINEBEFORE", (0, 0), (0, -1), 3, role_color),
                    ("LEFTPADDING", (0, 0), (-1, -1), 10),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                    ("TOPPADDING", (0, 0), (-1, 0), 7),
                    ("BOTTOMPADDING", (0, 0), (-1, 0), 2),
                    ("TOPPADDING", (0, 1), (-1, 1), 2),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 8),
                ]
            )
        )
        story.extend([KeepTogether(card), Spacer(1, 2.4 * mm)])

    def add_report(title: str, report: dict[str, Any], sections: list[tuple[str, str, str]], accent: Any) -> None:
        story.extend([PageBreak(), p(title, section_title)])
        for key, section_label, _ in sections:
            value = report.get(key)
            items = value if isinstance(value, list) else [value]
            items = items or [copy["fallback"]]
            content = [p(item or copy["fallback"]) for item in items]
            rows = [[p(section_label, label)]] + [[item] for item in content]
            card = Table(rows, colWidths=[content_width])
            card.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F3F7FA")),
                        ("BOX", (0, 0), (-1, -1), 0.7, line),
                        ("LINEBEFORE", (0, 0), (0, -1), 3, accent),
                        ("LEFTPADDING", (0, 0), (-1, -1), 10),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 10),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ]
                )
            )
            story.extend([KeepTogether(card), Spacer(1, 3 * mm)])

    add_report(copy["report"], report, sections, blue if is_doctor else teal)
    document.build(story, onFirstPage=page_decor, onLaterPages=page_decor)
    return buffer.getvalue()
