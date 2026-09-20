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

