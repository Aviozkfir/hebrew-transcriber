"""Application configuration, loaded from the project's .env file."""
import os
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = PROJECT_ROOT / "data"
RECORDINGS_DIR = DATA_DIR / "recordings"
RESPONSES_DIR = DATA_DIR / "responses"
DB_PATH = DATA_DIR / "transcriber.db"
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

PORT = int(os.getenv("PORT", "8765"))

# Fixed transcription settings (as specified; intentionally not user-configurable).
TRANSCRIPTION_SETTINGS = {
    "model_id": "scribe_v3",
    "language_code": "he",
    "diarize": True,
    # num_speakers is set per recording (MIN_SPEAKERS..MAX_SPEAKERS), see transcriber.py.
    "timestamps_granularity": "word",
    "no_verbatim": False,
    "tag_audio_events": False,
}

MIN_SPEAKERS = 2
MAX_SPEAKERS = 4

# How many recordings are sent to ElevenLabs at the same time.
MAX_CONCURRENT_TRANSCRIPTIONS = 2
# A 40-minute call can take several minutes to process; allow plenty of time.
REQUEST_TIMEOUT_SECONDS = 60 * 60

ALLOWED_EXTENSIONS = {".mp3", ".m4a", ".wav"}

for d in (DATA_DIR, RECORDINGS_DIR, RESPONSES_DIR):
    d.mkdir(parents=True, exist_ok=True)


def get_api_key() -> str | None:
    # Re-read so that editing .env takes effect without restarting.
    load_dotenv(PROJECT_ROOT / ".env", override=True)
    key = os.getenv("ELEVENLABS_API_KEY", "").strip()
    if not key or key == "your_api_key_here":
        return None
    return key
