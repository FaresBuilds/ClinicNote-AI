# Clinical Conversation Companion


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

## Demo accounts and report delivery

1. Create one Patient account and one Doctor account from separate browser sessions.
2. Log in as the Doctor and select the registered Patient email.
3. Process a consultation, review both reports, and select **Send to patient**.
4. Confirm both reports appear in **Report history** for the Doctor.
5. Log in as the Patient and confirm only the Patient Report appears.

On Streamlit Community Cloud, add `ELEVENLABS_API_KEY` and
`OPENROUTER_API_KEY` in the app's Secrets settings. SQLite and generated
reports are stored on the running app instance and may disappear after a
restart or redeployment. Register demonstration accounts shortly before
the presentation and avoid redeploying during it.

