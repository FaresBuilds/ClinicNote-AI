# Clinical Conversation Companion

A small Streamlit graduation-project demo that turns a doctor-patient recording into:

- a speaker-separated, timestamped transcript using ElevenLabs Scribe v2 Medical;
- a clinician-facing consultation report using Gemini through OpenRouter; and
- a simple-language patient report.

The application does not infer speaker roles. After transcription, you confirm which detected speaker is the Doctor and which is the Patient.

## Run locally

1. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

2. Keep these values in `.env`:

   ```text
   ELEVENLABS_API_KEY=...
   OPENROUTER_API_KEY=...
   ```

   `OPENROUTER_MODEL` is optional and defaults to `google/gemini-3.8-flash`.

3. Start the application:

   ```powershell
   streamlit run app.py
   ```

4. Open `http://localhost:8501`. To expose the local demo through ngrok:

   ```powershell
   ngrok http 8501
   ```

Generated audio, transcripts, and reports are saved under `data/`. This is an educational demonstration, not a production healthcare system.

The app sends audio to ElevenLabs for transcription and sends the role-labelled transcript to Gemini through OpenRouter for report generation. API keys stay in the local Python process and are never placed in browser code.
