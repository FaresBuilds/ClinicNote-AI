import os
from pathlib import Path

import requests
from dotenv import load_dotenv


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

load_dotenv()

API_KEY = os.getenv("ELEVENLABS_API_KEY")

if not API_KEY:
    raise RuntimeError(
        "ELEVENLABS_API_KEY was not found in your environment or .env file."
    )

API_BASE = "https://api.elevenlabs.io"
HEADERS = {"xi-api-key": API_KEY}

# Optional manual overrides. If both are present, the script skips voice discovery.
DOCTOR_VOICE_ID_ENV = os.getenv("ELEVENLABS_DOCTOR_VOICE_ID")
PATIENT_VOICE_ID_ENV = os.getenv("ELEVENLABS_PATIENT_VOICE_ID")

OUTPUT_DIR = Path("data/audio")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "test_doctor_patient_arabic.mp3"
TRANSCRIPT_FILE = OUTPUT_DIR / "test_doctor_patient_arabic_expected.txt"
VOICE_INFO_FILE = OUTPUT_DIR / "test_doctor_patient_arabic_voices.txt"


# ---------------------------------------------------------
# Voice discovery
# ---------------------------------------------------------

EGYPT_KEYWORDS = (
    "egypt",
    "egyptian",
    "cairo",
    "alexandria",
    "masri",
    "masry",
    "مصري",
    "مصرية",
    "مصر",
    "القاهرة",
)


def _safe_lower(value):
    return str(value or "").strip().lower()


def _voice_gender(voice):
    # Shared Voice Library results expose gender directly.
    gender = _safe_lower(voice.get("gender"))
    if gender:
        return gender

    # /v2/voices results usually put it in labels.
    labels = voice.get("labels") or {}
    return _safe_lower(labels.get("gender"))


def _voice_accent(voice):
    accent = _safe_lower(voice.get("accent"))
    if accent:
        return accent

    labels = voice.get("labels") or {}
    return _safe_lower(labels.get("accent"))


def _voice_language(voice):
    language = _safe_lower(voice.get("language"))
    if language:
        return language

    labels = voice.get("labels") or {}
    return _safe_lower(labels.get("language"))


def egyptian_score(voice):
    """
    Rank voices by how strongly their metadata suggests Egyptian Arabic.
    This intentionally uses several metadata fields because Voice Library
    entries are not always tagged consistently.
    """
    text_parts = [
        voice.get("name"),
        voice.get("description"),
        voice.get("accent"),
        voice.get("language"),
    ]

    labels = voice.get("labels") or {}
    text_parts.extend(
        [
            labels.get("accent"),
            labels.get("language"),
            labels.get("description"),
            labels.get("use_case"),
        ]
    )

    for verified in voice.get("verified_languages") or []:
        text_parts.extend(
            [
                verified.get("language"),
                verified.get("accent"),
                verified.get("locale"),
            ]
        )

    haystack = " ".join(_safe_lower(part) for part in text_parts if part)

    score = 0

    # Strong Egyptian markers.
    if "egyptian" in haystack:
        score += 100
    if "egypt" in haystack:
        score += 80
    if "cairo" in haystack:
        score += 70
    if "alexandria" in haystack:
        score += 60
    if "masri" in haystack or "masry" in haystack:
        score += 70
    if any(word in haystack for word in ("مصري", "مصرية", "مصر", "القاهرة")):
        score += 100

    # Arabic itself is still useful as a fallback.
    language = _voice_language(voice)
    if language in {"ar", "ara", "arabic"} or "arabic" in haystack:
        score += 20

    return score


def _request_json(url, params=None):
    response = requests.get(
        url,
        headers=HEADERS,
        params=params,
        timeout=30,
    )

    if response.ok:
        return response.json()

    if response.status_code in (401, 403):
        raise RuntimeError(
            "ElevenLabs rejected the voice lookup request.\n"
            "Make sure this API key has:\n"
            "  - Voices -> Read\n"
            "  - Text to Speech -> Access\n\n"
            f"HTTP {response.status_code}: {response.text}"
        )

    response.raise_for_status()


def get_egyptian_library_voices():
    """
    Search ElevenLabs' shared Voice Library for Arabic/Egyptian voices.

    The shared-voices endpoint supports language, accent/search, gender,
    and pagination. We use broad searches and then rank locally because
    metadata tags can vary between voice owners.
    """
    collected = {}

    searches = [
        {"language": "ar", "search": "egyptian"},
        {"language": "ar", "search": "egypt"},
        {"language": "ar", "search": "cairo"},
        {"language": "ar"},
    ]

    for extra_params in searches:
        params = {
            "page_size": 100,
            "include_custom_rates": False,
            "include_live_moderated": False,
            **extra_params,
        }

        try:
            data = _request_json(
                f"{API_BASE}/v1/shared-voices",
                params=params,
            )
        except requests.HTTPError:
            continue

        for voice in data.get("voices", []):
            voice_id = voice.get("voice_id")
            if voice_id:
                collected[voice_id] = voice

    voices = list(collected.values())
    voices.sort(key=egyptian_score, reverse=True)
    return voices


def get_account_arabic_voices():
    """
    Fallback: voices already available in the user's account/workspace.
    """
    data = _request_json(
        f"{API_BASE}/v2/voices",
        params=[
            ("page_size", 100),
            ("language", "ar"),
        ],
    )

    voices = data.get("voices", [])
    voices.sort(key=egyptian_score, reverse=True)
    return voices


def _pick_gender(voices, gender, used_ids=None, require_egyptian=False):
    used_ids = set(used_ids or [])

    candidates = []
    for voice in voices:
        voice_id = voice.get("voice_id")
        if not voice_id or voice_id in used_ids:
            continue

        if require_egyptian and egyptian_score(voice) < 60:
            continue

        voice_gender = _voice_gender(voice)

        # Prefer a matching gender, but keep unknown-gender voices available
        # as a fallback.
        gender_score = 10 if voice_gender == gender else 0
        if voice_gender and voice_gender != gender:
            gender_score = -10

        candidates.append(
            (
                egyptian_score(voice) + gender_score,
                voice,
            )
        )

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def choose_two_voices():
    # Manual IDs win. This is the most deterministic option.
    if DOCTOR_VOICE_ID_ENV and PATIENT_VOICE_ID_ENV:
        print("\nUsing voice IDs supplied in .env.")
        return (
            DOCTOR_VOICE_ID_ENV,
            PATIENT_VOICE_ID_ENV,
            {
                "doctor_name": "Manual .env voice",
                "patient_name": "Manual .env voice",
                "doctor_source": "environment",
                "patient_source": "environment",
            },
        )

    print("Searching ElevenLabs Voice Library for Egyptian Arabic voices...")

    library_voices = get_egyptian_library_voices()

    # Prefer a male doctor and female patient simply to make diarization
    # easier to hear in this test file.
    doctor = _pick_gender(
        library_voices,
        "male",
        require_egyptian=True,
    )

    patient = _pick_gender(
        library_voices,
        "female",
        used_ids={doctor["voice_id"]} if doctor else set(),
        require_egyptian=True,
    )

    source = "Egyptian Voice Library"

    # If we couldn't get a clearly Egyptian pair, use the best Arabic voices
    # available, still preferring Egyptian metadata.
    if not doctor or not patient:
        print(
            "Could not find a complete male/female Egyptian pair in the "
            "Voice Library. Falling back to the best Arabic voices available."
        )

        combined = list(library_voices)

        try:
            account_voices = get_account_arabic_voices()
            existing_ids = {v.get("voice_id") for v in combined}
            combined.extend(
                v for v in account_voices
                if v.get("voice_id") not in existing_ids
            )
        except Exception as exc:
            print(f"Account voice fallback was unavailable: {exc}")

        combined.sort(key=egyptian_score, reverse=True)

        doctor = doctor or _pick_gender(combined, "male")
        used = {doctor["voice_id"]} if doctor else set()
        patient = patient or _pick_gender(combined, "female", used_ids=used)

        # Last fallback: just use two different Arabic voices.
        if not doctor and combined:
            doctor = combined[0]

        if not patient:
            for voice in combined:
                if doctor and voice.get("voice_id") == doctor.get("voice_id"):
                    continue
                patient = voice
                break

        source = "Arabic fallback"

    if not doctor or not patient:
        raise RuntimeError(
            "I could not find two usable Arabic voices.\n\n"
            "Fastest fix:\n"
            "1. Open ElevenLabs -> Voices -> Explore.\n"
            "2. Filter Language = Arabic and Accent = Egyptian if available.\n"
            "3. Pick two voices and copy their voice IDs.\n"
            "4. Add these to .env:\n"
            "   ELEVENLABS_DOCTOR_VOICE_ID=...\n"
            "   ELEVENLABS_PATIENT_VOICE_ID=...\n"
        )

    doctor_id = doctor["voice_id"]
    patient_id = patient["voice_id"]

    print("\nUsing voices:")
    print(
        f"Doctor  : {doctor.get('name', 'Unknown')} | "
        f"gender={_voice_gender(doctor) or 'unknown'} | "
        f"accent={_voice_accent(doctor) or 'unknown'} | "
        f"score={egyptian_score(doctor)}"
    )
    print(
        f"Patient : {patient.get('name', 'Unknown')} | "
        f"gender={_voice_gender(patient) or 'unknown'} | "
        f"accent={_voice_accent(patient) or 'unknown'} | "
        f"score={egyptian_score(patient)}"
    )

    return (
        doctor_id,
        patient_id,
        {
            "doctor_name": doctor.get("name", "Unknown"),
            "patient_name": patient.get("name", "Unknown"),
            "doctor_accent": _voice_accent(doctor) or "unknown",
            "patient_accent": _voice_accent(patient) or "unknown",
            "doctor_score": egyptian_score(doctor),
            "patient_score": egyptian_score(patient),
            "doctor_source": source,
            "patient_source": source,
        },
    )


DOCTOR_VOICE_ID, PATIENT_VOICE_ID, VOICE_INFO = choose_two_voices()


# ---------------------------------------------------------
# Fake doctor/patient conversation
# Egyptian Arabic on purpose, so we can test Arabic STT.
# ---------------------------------------------------------

conversation = [
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": "أهلاً، اتفضلي. قوليلي مالك، إيه اللي تعبك؟",
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "بص يا دكتور، بقالي تقريباً أربع أيام عندي صداع مش بيروح، "
            "وحاسة إني مرهقة طول الوقت ومش قادرة أركز كويس."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "طيب، الصداع ده بييجي فين بالظبط؟ في ناحية معينة ولا في دماغك كلها؟"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "غالباً بيبقى من قدام، حوالين الجبهة وكده. "
            "وساعات بحس إنه بيزيد آخر اليوم."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "تمام. فيه دوخة؟ زغللة؟ ترجيع؟ أو حساسية زيادة من النور مثلاً؟"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "مفيش ترجيع، والزغللة لأ. بس امبارح وأنا بقوم من السرير "
            "حسيت بدوخة شوية، وبعدها راحت."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": "طيب، سخونية؟ برد؟ كحة؟ أي أعراض تانية؟",
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "مش متأكدة، بس حسيت إني سخنة شوية أول امبارح. "
            "مقستش الحرارة بصراحة. مفيش كحة ولا برد."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "ماشي. نومك عامل إيه اليومين دول؟ وبتاكلي وبتشربي مياه كويس؟"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "النوم وحش جداً بصراحة. عندي امتحانات، فبنام يمكن أربع أو خمس ساعات. "
            "وبشرب قهوة كتير، يمكن تلات أو أربع مجات في اليوم. "
            "والمياه مش بشرب كتير."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "آه، كده الصورة بدأت تبقى أوضح شوية. "
            "بس الأول، عندك أي أمراض مزمنة؟ ضغط، سكر، أنيميا، أي حاجة؟"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "لأ، معنديش حاجة على حد علمي. بس كان عندي أنيميا بسيطة "
            "من كام سنة وخدت حديد فترة وبطلت."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": "وبتاخدي أي أدوية دلوقتي؟",
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "لأ، مفيش أدوية ثابتة. خدت بس باراسيتامول مرتين عشان الصداع، "
            "وكان بيخف شوية وبعدها يرجع."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "تمام. أنا هقيسلك الضغط والحرارة دلوقتي، ونشوف الفحص عامل إيه. "
            "قلة النوم، القهوة الكتير، وقلة شرب المياه ممكن يكونوا عاملين جزء كبير "
            "من الصداع والإرهاق، بس طبعاً مش هنعتمد على ده لوحده."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "طب محتاجة أعمل تحاليل ولا مش ضروري؟",
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "لو الإرهاق والصداع فضلوا مستمرين، خصوصاً مع إن كان عندك أنيميا قبل كده، "
            "ممكن نعمل صورة دم كاملة ونشوف نسبة الهيموجلوبين. "
            "وبناءً على الفحص ممكن نحدد لو محتاجين تحاليل تانية."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "طيب أعمل إيه الفترة دي؟",
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "حاولي تنامي سبع ساعات على الأقل، وقللي القهوة بالتدريج، "
            "واشربي مياه كويس طول اليوم. وكلي وجبات منتظمة، خصوصاً الفترة دي."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "وأرجعلك إمتى لو الصداع مراحش؟",
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "لو خلال تلات أو أربع أيام مفيش تحسن، ارجعي نتابع ونعمل التحاليل. "
            "لكن لو الصداع فجأة بقى شديد جداً، أو حصل ترجيع متكرر، "
            "أو إغماء، أو ضعف في إيد أو رجل، ساعتها متستنيش وتروحي للطوارئ."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "تمام يا دكتور، فهمت. شكراً جداً.",
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": "العفو. ألف سلامة عليكي.",
    },
]

# ---------------------------------------------------------
# Generate dialogue
# ---------------------------------------------------------

url = (
    f"{API_BASE}/v1/text-to-dialogue"
    "?output_format=mp3_44100_128"
)

headers = {
    **HEADERS,
    "Content-Type": "application/json",
}

payload = {
    "model_id": "eleven_v3",
    "language_code": "ar",
    "inputs": [
        {
            "text": turn["text"],
            "voice_id": turn["voice_id"],
        }
        for turn in conversation
    ],
}

total_chars = sum(len(turn["text"]) for turn in conversation)
print(f"\nDialogue length: {total_chars} characters")
print("Generating Egyptian Arabic doctor/patient conversation...")

response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=180,
)

if not response.ok:
    print("\nElevenLabs dialogue generation failed.")
    print("Status:", response.status_code)
    print("Response:", response.text)

    if response.status_code in (401, 403):
        print(
            "\nCheck that the API key has Text to Speech -> Access "
            "and Voices -> Read."
        )

    if "voice_not_found" in response.text:
        print(
            "\nOne of the selected Voice Library voices is not usable "
            "with this account. Pick two Arabic/Egyptian voices manually "
            "in ElevenLabs and place their IDs in .env."
        )

    response.raise_for_status()


# ---------------------------------------------------------
# Save audio
# ---------------------------------------------------------

OUTPUT_FILE.write_bytes(response.content)

print("\nAudio generated successfully:")
print(f"  {OUTPUT_FILE.resolve()}")


# ---------------------------------------------------------
# Save the ground-truth transcript
# ---------------------------------------------------------

expected_transcript = "\n\n".join(
    f'{turn["speaker"]}: {turn["text"]}'
    for turn in conversation
)

TRANSCRIPT_FILE.write_text(
    expected_transcript,
    encoding="utf-8",
)

print("\nExpected transcript saved:")
print(f"  {TRANSCRIPT_FILE.resolve()}")


# ---------------------------------------------------------
# Save selected voice information
# ---------------------------------------------------------

voice_info_text = (
    f"Doctor voice ID: {DOCTOR_VOICE_ID}\n"
    f"Doctor name: {VOICE_INFO.get('doctor_name', 'Unknown')}\n"
    f"Doctor accent: {VOICE_INFO.get('doctor_accent', 'unknown')}\n"
    f"Doctor source: {VOICE_INFO.get('doctor_source', 'unknown')}\n\n"
    f"Patient voice ID: {PATIENT_VOICE_ID}\n"
    f"Patient name: {VOICE_INFO.get('patient_name', 'Unknown')}\n"
    f"Patient accent: {VOICE_INFO.get('patient_accent', 'unknown')}\n"
    f"Patient source: {VOICE_INFO.get('patient_source', 'unknown')}\n"
)

VOICE_INFO_FILE.write_text(
    voice_info_text,
    encoding="utf-8",
)

print("\nVoice information saved:")
print(f"  {VOICE_INFO_FILE.resolve()}")

print("\nDone.")
print(
    "Upload test_doctor_patient_arabic.mp3 to your Streamlit app "
    "and compare its transcription against "
    "test_doctor_patient_arabic_expected.txt."
)
