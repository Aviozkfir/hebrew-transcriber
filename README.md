# Hebrew Telephone Transcription

A local Windows application that transcribes Hebrew phone conversations between two to four people with **ElevenLabs Scribe v3**, then lets you assign real names to the voices, review and correct the transcript next to the audio, and export it.

- **Backend:** Python + FastAPI (`backend/`)
- **Frontend:** React + Vite (`frontend/`, prebuilt into `frontend/dist`)
- **Storage:** SQLite and local files (`data/`)
- **Transcription:** official `elevenlabs` Python SDK

Everything runs on your computer. The API key stays in `.env` and is used only by the local backend. It is never sent to the browser. The server listens on `127.0.0.1` only.

---

## Setup (once)

Requirements: **Windows 10 or 11** and an internet connection. Everything else is installed automatically by `start.bat`.

1. Copy this `hebrew-transcriber` folder anywhere on your computer.
2. Python 3.10 or newer is needed. If it is not installed, `start.bat` installs Python 3.12 for you on the first run, for your user only and without administrator rights. It uses `winget`, or downloads the official installer from python.org if `winget` is not available. To install it yourself instead, get it from <https://www.python.org/downloads/> and tick **"Add python.exe to PATH"**.
3. Create your key file: copy `.env.example` to `.env` and paste your ElevenLabs API key:
   ```
   ELEVENLABS_API_KEY=sk_...
   ```
   You can skip this step. If `.env` is missing on the first run, `start.bat` creates it and opens it in Notepad for you.

Node.js is **not** required, because the interface is already built. You only need it if you change the frontend code (see *Development*).

## Start

Double-click **`start.bat`**, or run it from a terminal:

```bat
start.bat
```

On the first run it installs Python if needed, creates a virtual environment (`.venv`) and installs the dependencies, which takes a few minutes. It then starts the server and opens <http://127.0.0.1:8765> in your browser. To stop the app, close the console window.

## Workflow

1. **Upload** one or more recordings (MP3, M4A, WAV). Drag them in or click the upload box.
2. **Choose the number of speakers and enter their names.** Pick how many people are in the call (2, 3 or 4) under *מספר דוברים בשיחה*, then type a name for each. This number is sent to ElevenLabs, so set it before transcribing. Names and the count are saved per recording. If you upload several calls with the same people, click *"החל את מספר הדוברים והשמות על כל ההקלטות שטרם תומללו"* to copy them to the other recordings.
3. Click **תמלל** (Transcribe), or **"תמלל את כל הממתינות"** to transcribe every pending recording. Each recording is sent to ElevenLabs as one whole file, with no chunking. The interface stays usable while transcription runs in the background, and the status and elapsed time are shown.
4. **Confirm the speakers.** The transcript first shows the detected voices as *דובר 1*, *דובר 2* and so on. Play the short sample for each voice and choose which name it belongs to. Choosing a name that another voice already has swaps the two. With two speakers you can also click *⇄ החלף*. Then click **אישור שיוך**. ElevenLabs can occasionally confuse two similar voices (for example two men on a phone line); fix any wrong sentence with the speaker chip next to it. The names then appear throughout the transcript.
5. **Correct** the transcript if needed:
   - Click a sentence or its timestamp to jump the player there. The sentence that is playing is highlighted.
   - Edit text directly in place.
   - Change the speaker of any single sentence with the name chip next to it.
   - Every change saves automatically. Edited sentences are tinted, and **↺** restores the original text and speaker.
6. **Export** one transcript (DOCX, TXT, SRT, JSON) from the transcript header, or all transcripts at once from the bottom of the sidebar. TXT, DOCX and JSON produce one combined file. SRT produces a ZIP with one file per recording.

## Transcription settings

These are fixed in `backend/app/config.py` and passed directly to `client.speech_to_text.convert(...)`:

| Parameter | Value |
|---|---|
| `model_id` | `"scribe_v3"` |
| `language_code` | `"he"` |
| `diarize` | `True` |
| `num_speakers` | chosen per recording: `2`, `3` or `4` (default `2`) |
| `timestamps_granularity` | `"word"` |
| `no_verbatim` | `False` (keeps fillers, repetitions, false starts) |
| `tag_audio_events` | `False` (no laughter or noise labels) |

Fidelity guarantees:
- Sentence text is the exact concatenation of the words returned by the API. Nothing is rewritten, summarised or translated.
- Audio-event tokens are dropped. With `tag_audio_events=False` none are expected, so this is a safety net.
- The **complete original API response** is saved unchanged in `data/responses/<id>.json`. You can download it with the *"API מקורי"* button.
- Manual edits are stored separately from the original text, speaker and word-level timestamps, so the originals are never lost.

## Export formats

All exports use the real speaker names, chronological order and timestamps.

- **TXT**: `[00:01:12] דני: …`, UTF-8 with BOM, and each line starts with a right-to-left mark (RLM) so it displays RTL in Windows apps.
- **DOCX**: right-to-left paragraphs, David font, grey timestamps and bold names.
- **SRT**: standard subtitles with `Name: text`, aligned to the audio.
- **JSON**: speakers, sentences (current text plus original text), and all word-level data.

## Where data is stored

```
data/
  transcriber.db        SQLite: recordings, speaker mappings, sentences and edits
  recordings/           the original uploaded audio files
  responses/            the complete raw ElevenLabs responses (JSON)
```

To back up everything, copy the `data` folder. Deleting a recording in the app also deletes its audio and response files.

## Troubleshooting

| Message | Fix |
|---|---|
| "לא הוגדר מפתח API" | Add `ELEVENLABS_API_KEY` to `.env`. It is read again on each transcription, so you don't need to restart. |
| "מפתח ה-API אינו תקין (401)" | The key is wrong or was revoked. |
| "אין מספיק קרדיט (402)" | Top up your ElevenLabs account. |
| "לא ניתן להתחבר ל-ElevenLabs" | Check your internet connection, firewall or proxy. |
| "Could not install packages due to an OSError … Long Path" | Windows limits file paths to 260 characters. `start.bat` asks to enable long paths (click **Yes** on the Windows prompt). If you decline, it keeps the Python environment in `C:\htenv` instead. You can also move the app to a short folder such as `D:\ht`. Delete the `.venv` folder before running `start.bat` again. |
| Port already in use | Set `PORT=8766` (or another free port) in `.env`. |

If the app is closed during a transcription, that recording is queued again automatically the next time the app starts.

## Development

```bat
:: backend with auto-reload
.venv\Scripts\python -m uvicorn app.main:app --app-dir backend --reload --port 8765

:: frontend dev server (proxies /api to the backend) at http://localhost:5173
cd frontend
npm install
npm run dev

:: rebuild the bundled interface after changing frontend code
npm run build
```
