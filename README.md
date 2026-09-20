# Clinical Conversation Companion

A small Streamlit graduation-project demo that turns a doctor-patient recording into:

- a speaker-separated, timestamped transcript using ElevenLabs Scribe v2 Medical;
- a clinician-facing consultation report using Gemini through OpenRouter; and
- a simple-language patient report.

The application does not infer speaker roles. After transcription, you confirm which detected speaker is the Doctor and which is the Patient.

Choose **English** or **العربية** at the top of the app before adding audio. The selection sets the expected transcription language and the language used for both reports.

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

For **Record now**, open the app directly in Chrome or Edge and allow microphone access when
prompted. Use `localhost` on the same computer or the HTTPS ngrok URL; browsers block microphone
capture on plain-HTTP network addresses such as `http://192.168.x.x:8501`, and embedded previews
may not expose a microphone.

Generated audio, transcripts, and reports are saved under `data/`. This is an educational demonstration, not a production healthcare system.

The app sends audio to ElevenLabs for transcription and sends the role-labelled transcript to Gemini through OpenRouter for report generation. API keys stay in the local Python process and are never placed in browser code.
