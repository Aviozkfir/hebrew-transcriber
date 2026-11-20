"""Background transcription queue using the official ElevenLabs Python SDK."""
import asyncio
import json
import logging
from pathlib import Path

import httpx
from elevenlabs.client import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError

from . import db
from .config import (
    MAX_CONCURRENT_TRANSCRIPTIONS,
    RECORDINGS_DIR,
    REQUEST_TIMEOUT_SECONDS,
    RESPONSES_DIR,
    TRANSCRIPTION_SETTINGS,
    get_api_key,
)
from .segmenter import build_segments

log = logging.getLogger("transcriber")

_queue: asyncio.Queue[int] = asyncio.Queue()
_workers: list[asyncio.Task] = []


class TranscriptionError(Exception):
    pass


def _set_status(rec_id: int, status: str, **fields) -> None:
    cols = {"status": status, "updated_at": db.now_iso(), **fields}
    sets = ", ".join(f"{k} = ?" for k in cols)
    with db.tx() as c:
        c.execute(f"UPDATE recordings SET {sets} WHERE id = ?", (*cols.values(), rec_id))


def _describe_api_error(e: ApiError) -> str:
    body = e.body
    detail = None
    if isinstance(body, dict):
        d = body.get("detail", body)
        if isinstance(d, dict):
            detail = d.get("message") or d.get("status") or json.dumps(d, ensure_ascii=False)
        else:
            detail = str(d)
    elif body:
        detail = str(body)
    code = e.status_code
    hints = {
        401: "מפתח ה-API אינו תקין (401). בדקו את ELEVENLABS_API_KEY בקובץ ‎.env",
        402: "אין מספיק קרדיט בחשבון ElevenLabs (402).",
        413: "הקובץ גדול מדי עבור ElevenLabs (413).",
        422: "ElevenLabs דחה את הבקשה (422).",
        429: "חריגה ממגבלת הבקשות של ElevenLabs (429). נסו שוב בעוד מספר דקות.",
    }
    head = hints.get(code, f"שגיאת ElevenLabs ({code}).")
    return f"{head} {detail}" if detail else head


async def _call_elevenlabs(audio_path: Path, filename: str) -> dict:
    api_key = get_api_key()
    if not api_key:
        raise TranscriptionError("לא הוגדר מפתח API. הוסיפו ELEVENLABS_API_KEY לקובץ ‎.env והפעילו מחדש.")

    client = AsyncElevenLabs(api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS)
    # The whole recording is sent as a single file (no chunking).
    with open(audio_path, "rb") as f:
        raw = await client.speech_to_text.with_raw_response.convert(
            file=(filename, f),
            **TRANSCRIPTION_SETTINGS,
            request_options={"timeout_in_seconds": REQUEST_TIMEOUT_SECONDS, "max_retries": 2},
        )
    # Keep the complete, unmodified API response body.
    http_response = getattr(raw, "_response", None)
    if http_response is not None:
        try:
            return http_response.json()
        except Exception:  # pragma: no cover - fall back to the parsed model
            pass
    return raw.data.model_dump(mode="json")


def save_transcription(rec_id: int, response: dict) -> None:
    """Persist the raw response and derived segments/speakers for a recording."""
    response_file = f"{rec_id}.json"
    (RESPONSES_DIR / response_file).write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding="utf-8")

    segments, speaker_order = build_segments(response)
    # Always offer two speakers, even if diarization found only one.
    for fallback in ("speaker_0", "speaker_1"):
        if len(speaker_order) >= 2:
            break
        if fallback not in speaker_order:
            speaker_order.append(fallback)

    duration = response.get("audio_duration_secs")
    if duration is None and segments:
        duration = segments[-1]["end"]

    with db.tx() as c:
        c.execute("DELETE FROM segments WHERE recording_id = ?", (rec_id,))
        c.execute("DELETE FROM speakers WHERE recording_id = ?", (rec_id,))
        for i, sp in enumerate(speaker_order, start=1):
            slot = 1 if i == 1 else 2 if i == 2 else ((i - 1) % 2) + 1
            c.execute(
                "INSERT INTO speakers (recording_id, speaker_id, label_index, slot) VALUES (?, ?, ?, ?)",
                (rec_id, sp, i, slot),
            )
        for i, s in enumerate(segments):
            c.execute(
                """INSERT INTO segments (recording_id, idx, start, end, speaker_id, original_speaker_id,
                                         text, original_text, words_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)""",
                (
                    rec_id, i, s["start"], s["end"], s["speaker_id"], s["speaker_id"],
                    s["text"], s["text"], json.dumps(s["tokens"], ensure_ascii=False),
                ),
            )
        c.execute(
            """UPDATE recordings SET status = 'done', error = NULL, finished_at = ?, updated_at = ?,
                      duration_secs = ?, language_code = ?, response_file = ?, speakers_confirmed = 0
               WHERE id = ?""",
            (db.now_iso(), db.now_iso(), duration, response.get("language_code"), response_file, rec_id),
        )


async def _process(rec_id: int) -> None:
    rec = db.query_one("SELECT * FROM recordings WHERE id = ?", (rec_id,))
    if not rec or rec["status"] != "queued":
        return
    _set_status(rec_id, "transcribing", started_at=db.now_iso(), finished_at=None, error=None)
    log.info("Transcribing recording %s (%s)", rec_id, rec["filename"])
    try:
        response = await _call_elevenlabs(RECORDINGS_DIR / rec["stored_name"], rec["filename"])
        if "words" not in response:
            raise TranscriptionError("התקבלה תשובה לא צפויה מ-ElevenLabs (חסר שדה words).")
        await asyncio.to_thread(save_transcription, rec_id, response)
        log.info("Recording %s done", rec_id)
    except ApiError as e:
        log.warning("ElevenLabs API error for %s: %s", rec_id, e)
        _set_status(rec_id, "error", error=_describe_api_error(e), finished_at=db.now_iso())
    except TranscriptionError as e:
        _set_status(rec_id, "error", error=str(e), finished_at=db.now_iso())
    except httpx.TimeoutException:
        _set_status(rec_id, "error", finished_at=db.now_iso(),
                    error="תם הזמן להמתנה לתשובה מ-ElevenLabs. נסו שוב.")
    except httpx.TransportError as e:
        log.warning("Network error for %s: %s", rec_id, e)
        _set_status(rec_id, "error", finished_at=db.now_iso(),
                    error=f"לא ניתן להתחבר ל-ElevenLabs. בדקו את החיבור לאינטרנט. ({type(e).__name__}: {e})")
    except Exception as e:  # network errors, timeouts, etc.
        log.exception("Transcription failed for %s", rec_id)
        _set_status(rec_id, "error", error=f"התמלול נכשל: {type(e).__name__}: {e}", finished_at=db.now_iso())


async def _worker() -> None:
    while True:
        rec_id = await _queue.get()
        try:
            await _process(rec_id)
        finally:
            _queue.task_done()


def start_workers() -> None:
    for _ in range(MAX_CONCURRENT_TRANSCRIPTIONS):
        _workers.append(asyncio.create_task(_worker()))
    # Resume anything that was queued or interrupted when the app last closed.
    with db.tx() as c:
        c.execute("UPDATE recordings SET status = 'queued' WHERE status = 'transcribing'")
    for r in db.query("SELECT id FROM recordings WHERE status = 'queued' ORDER BY id"):
        _queue.put_nowait(r["id"])


async def stop_workers() -> None:
    for w in _workers:
        w.cancel()
    _workers.clear()


def enqueue(rec_id: int) -> None:
    _set_status(rec_id, "queued", error=None, started_at=None, finished_at=None)
    _queue.put_nowait(rec_id)
