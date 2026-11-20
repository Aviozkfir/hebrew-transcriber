"""Start the local server and open the browser."""
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import PORT, get_api_key  # noqa: E402

if __name__ == "__main__":
    url = f"http://127.0.0.1:{PORT}"
    print(f"\n  Hebrew transcription app running at {url}")
    if get_api_key() is None:
        print("  WARNING: ELEVENLABS_API_KEY is not set in .env - transcription will not work until you add it.")
    print("  Close this window (or press Ctrl+C) to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    # Bound to localhost only: the app is not reachable from other computers.
    uvicorn.run("app.main:app", host="127.0.0.1", port=PORT, log_level="info")
