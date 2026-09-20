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

# You can override these in .env later.
# These defaults are voice IDs used in ElevenLabs' own API examples.
# ---------------------------------------------------------
# Automatically choose two available English voices
# ---------------------------------------------------------

def get_available_voices():
    url = "https://api.elevenlabs.io/v2/voices"

    headers = {
        "xi-api-key": API_KEY,
    }

    params = {
        "page_size": 100,
        "language": "en",
    }

    response = requests.get(
        url,
        headers=headers,
        params=params,
        timeout=30,
    )

    if not response.ok:
        print("Failed to retrieve ElevenLabs voices.")
        print("Status:", response.status_code)
        print("Response:", response.text)
        response.raise_for_status()

    voices = response.json().get("voices", [])

    if len(voices) < 2:
        raise RuntimeError(
            "Your ElevenLabs account does not have at least two "
            "available voices. Add voices in ElevenLabs first."
        )

    return voices


def choose_two_voices():
    voices = get_available_voices()

    male_voices = []
    female_voices = []

    for voice in voices:
        labels = voice.get("labels") or {}
        gender = str(labels.get("gender", "")).lower()

        if gender == "male":
            male_voices.append(voice)
        elif gender == "female":
            female_voices.append(voice)

    # Prefer different genders to make diarization very obvious.
    if male_voices and female_voices:
        doctor = male_voices[0]
        patient = female_voices[0]
    else:
        doctor = voices[0]
        patient = voices[1]

    print("\nUsing voices:")
    print(
        f"Doctor  : {doctor.get('name', 'Unknown')} "
        f"({doctor['voice_id']})"
    )
    print(
        f"Patient : {patient.get('name', 'Unknown')} "
        f"({patient['voice_id']})"
    )

    return doctor["voice_id"], patient["voice_id"]


DOCTOR_VOICE_ID, PATIENT_VOICE_ID = choose_two_voices()

OUTPUT_DIR = Path("data/audio")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "test_doctor_patient.mp3"
TRANSCRIPT_FILE = OUTPUT_DIR / "test_doctor_patient_expected.txt"


# ---------------------------------------------------------
# Fake doctor/patient conversation
# Egyptian Arabic on purpose, so we can test Arabic STT.
# ---------------------------------------------------------

conversation = [
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": "Good morning. What brings you in today?",
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "I've been having headaches and feeling unusually tired "
            "for about three days."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "Can you describe the headache? Where do you feel it, "
            "and how severe is the pain?"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "It's mostly around the front of my head. "
            "I'd say it's about a five out of ten. "
            "It usually gets worse in the afternoon."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "Have you had any fever, vomiting, blurred vision, "
            "dizziness, or weakness?"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "No vomiting or weakness. I felt slightly dizzy yesterday, "
            "and I think I had a mild fever last night."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "How have you been sleeping recently? "
            "And are you drinking enough water?"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "Not very well. I've been studying for exams, "
            "so I'm probably sleeping about four or five hours a night. "
            "I've also been drinking a lot of coffee and probably not enough water."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "Are you currently taking any medications, "
            "or do you have any medical conditions I should know about?"
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": (
            "No chronic medical conditions. "
            "I've only taken paracetamol twice for the headache."
        ),
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "Okay. Lack of sleep and dehydration may be contributing to your symptoms. "
            "I'd like to check your blood pressure and temperature today."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "Do you think I need any blood tests?",
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "If the fatigue and headaches continue, I may request a complete blood count "
            "and some additional blood tests depending on the examination. "
            "For now, increase your water intake, reduce your caffeine, "
            "and try to get seven to eight hours of sleep."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "Okay. When should I come back?",
    },
    {
        "speaker": "Doctor",
        "voice_id": DOCTOR_VOICE_ID,
        "text": (
            "If you're not improving within three to five days, schedule a follow-up appointment. "
            "If you develop a sudden severe headache, repeated vomiting, confusion, "
            "vision problems, or weakness in an arm or leg, seek medical attention immediately."
        ),
    },
    {
        "speaker": "Patient",
        "voice_id": PATIENT_VOICE_ID,
        "text": "Understood. Thank you, doctor.",
    },
]

# ---------------------------------------------------------
# Generate dialogue
# ---------------------------------------------------------

url = (
    "https://api.elevenlabs.io/v1/text-to-dialogue"
    "?output_format=mp3_44100_128"
)

headers = {
    "xi-api-key": API_KEY,
    "Content-Type": "application/json",
}

payload = {
    "model_id": "eleven_v3",
    "inputs": [
        {
            "text": turn["text"],
            "voice_id": turn["voice_id"],
        }
        for turn in conversation
    ],
}

print("Generating doctor/patient conversation...")

response = requests.post(
    url,
    headers=headers,
    json=payload,
    timeout=120,
)

if not response.ok:
    print("\nElevenLabs request failed.")
    print("Status:", response.status_code)
    print("Response:", response.text)
    response.raise_for_status()


# ---------------------------------------------------------
# Save audio
# ---------------------------------------------------------

OUTPUT_FILE.write_bytes(response.content)

print(f"\nAudio generated successfully:")
print(f"  {OUTPUT_FILE.resolve()}")


# ---------------------------------------------------------
# Also save the ground-truth transcript
# ---------------------------------------------------------

expected_transcript = "\n\n".join(
    f'{turn["speaker"]}: {turn["text"]}'
    for turn in conversation
)

TRANSCRIPT_FILE.write_text(
    expected_transcript,
    encoding="utf-8",
)

print(f"\nExpected transcript saved:")
print(f"  {TRANSCRIPT_FILE.resolve()}")

print("\nDone.")
print(
    "Upload test_doctor_patient.mp3 to your Streamlit app "
    "and compare its transcription against the expected transcript."
)