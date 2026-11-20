"""FastAPI application: REST API + serves the built React frontend."""
import io
import json
import logging
import uuid
import zipfile
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, exporters, transcriber
from .pitch import assign_slots
from .config import (
    ALLOWED_EXTENSIONS,
    FRONTEND_DIST,
    MAX_SPEAKERS,
    MIN_SPEAKERS,
    RECORDINGS_DIR,
    RESPONSES_DIR,
    get_api_key,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    transcriber.start_workers()
    yield
    await transcriber.stop_workers()


app = FastAPI(title="Hebrew Telephone Transcription", lifespan=lifespan)


# ---------------------------------------------------------------- helpers
def _get_rec(rec_id: int) -> dict:
    rec = db.query_one("SELECT * FROM recordings WHERE id = ?", (rec_id,))
    if not rec:
        raise HTTPException(404, "ההקלטה לא נמצאה")
    return rec


def _speakers(rec_id: int) -> list[dict]:
    return db.query("SELECT * FROM speakers WHERE recording_id = ? ORDER BY label_index", (rec_id,))


def _segments(rec_id: int, with_words: bool = False) -> list[dict]:
    cols = "*" if with_words else "id, recording_id, idx, start, end, speaker_id, original_speaker_id, text, original_text, updated_at"
    return db.query(f"SELECT {cols} FROM segments WHERE recording_id = ? ORDER BY start, idx", (rec_id,))


def _public_rec(rec: dict) -> dict:
    out = {k: v for k, v in rec.items() if k not in ("stored_name",)}
    out["segment_count"] = (db.query_one("SELECT COUNT(*) AS n FROM segments WHERE recording_id = ?", (rec["id"],)) or {}).get("n", 0)
    return out


def _download(content: bytes, filename: str, media_type: str) -> Response:
    ascii_name = filename.encode("ascii", "ignore").decode().strip(" .") or "transcript"
    if "." not in ascii_name and "." in filename:
        ascii_name += "." + filename.rsplit(".", 1)[1]
    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"},
    )


def _stem(filename: str) -> str:
    return Path(filename).stem or "transcript"


# ---------------------------------------------------------------- status
@app.get("/api/health")
def health():
    return {"ok": True, "api_key_configured": get_api_key() is not None}


# ---------------------------------------------------------------- recordings
@app.get("/api/recordings")
def list_recordings():
    return [_public_rec(r) for r in db.query("SELECT * FROM recordings ORDER BY id DESC")]


# Speaker settings copied from the latest recording to each new upload.
CARRY_OVER = ("num_speakers", "name1", "name2", "name3", "name4", "female_slot")


@app.post("/api/recordings")
async def upload_recordings(files: list[UploadFile] = File(...)):
    created = []
    for up in files:
        ext = Path(up.filename or "").suffix.lower()
        if ext not in ALLOWED_EXTENSIONS:
            raise HTTPException(400, f"סוג קובץ לא נתמך: {up.filename}. ניתן להעלות MP3, M4A או WAV בלבד.")
        stored = f"{uuid.uuid4().hex}{ext}"
        size = 0
        with open(RECORDINGS_DIR / stored, "wb") as out:
            while chunk := await up.read(1024 * 1024):
                out.write(chunk)
                size += len(chunk)
        now = db.now_iso()
        # Calls are usually with the same people: start from the latest recording's speakers.
        last = db.query_one(f"SELECT {', '.join(CARRY_OVER)} FROM recordings ORDER BY id DESC LIMIT 1") or {}
        carried = {k: last[k] for k in CARRY_OVER if k in last}
        cols = ["filename", "stored_name", "size_bytes", "created_at", "updated_at", *carried]
        with db.tx() as c:
            cur = c.execute(
                f"INSERT INTO recordings ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                (up.filename, stored, size, now, now, *carried.values()),
            )
            created.append(cur.lastrowid)
    return [_public_rec(_get_rec(i)) for i in created]


@app.get("/api/recordings/{rec_id}")
def get_recording(rec_id: int):
    rec = _get_rec(rec_id)
    return {"recording": _public_rec(rec), "speakers": _speakers(rec_id), "segments": _segments(rec_id)}


class RecordingPatch(BaseModel):
    name1: str | None = None
    name2: str | None = None
    name3: str | None = None
    name4: str | None = None
    num_speakers: int | None = None
    female_slot: int | None = None  # 0 = nobody marked as the woman


@app.patch("/api/recordings/{rec_id}")
def patch_recording(rec_id: int, body: RecordingPatch):
    _get_rec(rec_id)
    fields = {k: v.strip() if isinstance(v, str) else v for k, v in body.model_dump(exclude_none=True).items()}
    if "num_speakers" in fields and not MIN_SPEAKERS <= fields["num_speakers"] <= MAX_SPEAKERS:
        raise HTTPException(400, f"מספר הדוברים חייב להיות בין {MIN_SPEAKERS} ל-{MAX_SPEAKERS}")
    if "female_slot" in fields and not 0 <= fields["female_slot"] <= MAX_SPEAKERS:
        raise HTTPException(400, "סימון לא תקין")
    if fields:
        fields["updated_at"] = db.now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.tx() as c:
            c.execute(f"UPDATE recordings SET {sets} WHERE id = ?", (*fields.values(), rec_id))
    return _public_rec(_get_rec(rec_id))


@app.delete("/api/recordings/{rec_id}")
def delete_recording(rec_id: int):
    rec = _get_rec(rec_id)
    if rec["status"] == "transcribing":
        raise HTTPException(409, "לא ניתן למחוק הקלטה בזמן תמלול")
    with db.tx() as c:
        c.execute("DELETE FROM segments WHERE recording_id = ?", (rec_id,))
        c.execute("DELETE FROM speakers WHERE recording_id = ?", (rec_id,))
        c.execute("DELETE FROM recordings WHERE id = ?", (rec_id,))
    (RECORDINGS_DIR / rec["stored_name"]).unlink(missing_ok=True)
    if rec.get("response_file"):
        (RESPONSES_DIR / rec["response_file"]).unlink(missing_ok=True)
    return {"ok": True}


@app.post("/api/recordings/{rec_id}/transcribe")
def transcribe(rec_id: int, force: bool = False):
    rec = _get_rec(rec_id)
    if rec["status"] in ("queued", "transcribing"):
        return _public_rec(rec)
    if rec["status"] == "done" and not force:
        raise HTTPException(409, "ההקלטה כבר תומללה")
    if get_api_key() is None:
        raise HTTPException(400, "לא הוגדר מפתח API. הוסיפו ELEVENLABS_API_KEY לקובץ ‎.env")
    transcriber.enqueue(rec_id)
    return _public_rec(_get_rec(rec_id))


@app.get("/api/recordings/{rec_id}/audio")
def get_audio(rec_id: int):
    rec = _get_rec(rec_id)
    path = RECORDINGS_DIR / rec["stored_name"]
    if not path.exists():
        raise HTTPException(404, "קובץ השמע חסר")
    media = {".mp3": "audio/mpeg", ".m4a": "audio/mp4", ".wav": "audio/wav"}.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media)  # supports HTTP Range for seeking


@app.get("/api/recordings/{rec_id}/raw")
def get_raw_response(rec_id: int):
    rec = _get_rec(rec_id)
    if not rec.get("response_file") or not (RESPONSES_DIR / rec["response_file"]).exists():
        raise HTTPException(404, "אין תשובת API שמורה להקלטה זו")
    content = (RESPONSES_DIR / rec["response_file"]).read_bytes()
    return _download(content, f"{_stem(rec['filename'])}.elevenlabs.json", "application/json")


# ---------------------------------------------------------------- speakers & segments
class SpeakerMapping(BaseModel):
    mapping: dict[str, int]  # speaker_id -> slot (1 or 2)
    confirmed: bool | None = None


@app.put("/api/recordings/{rec_id}/speakers")
def set_speakers(rec_id: int, body: SpeakerMapping):
    _get_rec(rec_id)
    known = {s["speaker_id"] for s in _speakers(rec_id)}
    with db.tx() as c:
        for sp, slot in body.mapping.items():
            if sp not in known or not 1 <= slot <= MAX_SPEAKERS:
                raise HTTPException(400, "מיפוי דוברים לא תקין")
            c.execute("UPDATE speakers SET slot = ? WHERE recording_id = ? AND speaker_id = ?", (slot, rec_id, sp))
        if body.confirmed is not None:
            c.execute("UPDATE recordings SET speakers_confirmed = ?, updated_at = ? WHERE id = ?",
                      (1 if body.confirmed else 0, db.now_iso(), rec_id))
    return {"speakers": _speakers(rec_id), "recording": _public_rec(_get_rec(rec_id))}


@app.post("/api/recordings/{rec_id}/auto-assign")
def auto_assign(rec_id: int):
    """Re-apply the automatic voice -> name assignment (speaking order + woman's voice)."""
    rec = _get_rec(rec_id)
    speakers = _speakers(rec_id)
    if not speakers:
        raise HTTPException(409, f"ההקלטה {rec['filename']} עדיין לא תומללה")
    order = [s["speaker_id"] for s in speakers]  # already in order of first appearance
    pitches = {s["speaker_id"]: s["pitch_hz"] for s in speakers if s["pitch_hz"]}
    slots = assign_slots(order, transcriber.clamp_speakers(rec["num_speakers"]), rec["female_slot"], pitches)
    with db.tx() as c:
        for sp, slot in slots.items():
            c.execute("UPDATE speakers SET slot = ? WHERE recording_id = ? AND speaker_id = ?", (slot, rec_id, sp))
    return {"speakers": _speakers(rec_id), "recording": _public_rec(_get_rec(rec_id))}


class SegmentPatch(BaseModel):
    text: str | None = None
    speaker_id: str | None = None


def _get_segment(seg_id: int) -> dict:
    seg = db.query_one("SELECT * FROM segments WHERE id = ?", (seg_id,))
    if not seg:
        raise HTTPException(404, "המשפט לא נמצא")
    return seg


def _public_seg(seg_id: int) -> dict:
    seg = _get_segment(seg_id)
    seg.pop("words_json", None)
    return seg


@app.patch("/api/segments/{seg_id}")
def patch_segment(seg_id: int, body: SegmentPatch):
    seg = _get_segment(seg_id)
    fields = {}
    if body.text is not None:
        fields["text"] = body.text
    if body.speaker_id is not None:
        if body.speaker_id not in {s["speaker_id"] for s in _speakers(seg["recording_id"])}:
            raise HTTPException(400, "דובר לא מוכר")
        fields["speaker_id"] = body.speaker_id
    if fields:
        fields["updated_at"] = db.now_iso()
        sets = ", ".join(f"{k} = ?" for k in fields)
        with db.tx() as c:
            c.execute(f"UPDATE segments SET {sets} WHERE id = ?", (*fields.values(), seg_id))
    return _public_seg(seg_id)


@app.post("/api/segments/{seg_id}/revert")
def revert_segment(seg_id: int):
    _get_segment(seg_id)
    with db.tx() as c:
        c.execute("UPDATE segments SET text = original_text, speaker_id = original_speaker_id, updated_at = ? WHERE id = ?",
                  (db.now_iso(), seg_id))
    return _public_seg(seg_id)


# ---------------------------------------------------------------- export
FORMATS = {"txt", "docx", "srt", "json"}


def _export_one(rec: dict, fmt: str) -> tuple[bytes, str, str]:
    speakers, segments = _speakers(rec["id"]), _segments(rec["id"], with_words=(fmt == "json"))
    stem = _stem(rec["filename"])
    if fmt == "txt":
        return exporters.txt_bytes(exporters.to_txt(rec, speakers, segments)), f"{stem}.txt", "text/plain; charset=utf-8"
    if fmt == "srt":
        return exporters.txt_bytes(exporters.to_srt(rec, speakers, segments)), f"{stem}.srt", "application/x-subrip; charset=utf-8"
    if fmt == "json":
        data = json.dumps(exporters.to_json_obj(rec, speakers, segments), ensure_ascii=False, indent=2).encode("utf-8")
        return data, f"{stem}.json", "application/json"
    return (exporters.to_docx([(rec, speakers, segments)]), f"{stem}.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document")


def _done_rec(rec_id: int) -> dict:
    rec = _get_rec(rec_id)
    if rec["status"] != "done":
        raise HTTPException(409, f"ההקלטה {rec['filename']} עדיין לא תומללה")
    return rec


@app.get("/api/recordings/{rec_id}/export")
def export_one(rec_id: int, format: str = Query("txt")):
    if format not in FORMATS:
        raise HTTPException(400, "פורמט לא נתמך")
    content, name, media = _export_one(_done_rec(rec_id), format)
    return _download(content, name, media)


@app.get("/api/export")
def export_all(format: str = Query("txt"), ids: str | None = Query(None)):
    """All transcribed recordings together: one combined file (TXT/DOCX/JSON) or a ZIP of SRT files."""
    if format not in FORMATS:
        raise HTTPException(400, "פורמט לא נתמך")
    if ids:
        recs = [_done_rec(int(i)) for i in ids.split(",") if i.strip()]
    else:
        recs = db.query("SELECT * FROM recordings WHERE status = 'done' ORDER BY created_at, id")
    if not recs:
        raise HTTPException(404, "אין תמלולים מוכנים לייצוא")

    if format == "txt":
        sep = "\r\n" + "=" * 60 + "\r\n\r\n"
        text = sep.join(exporters.to_txt(r, _speakers(r["id"]), _segments(r["id"])) for r in recs)
        return _download(exporters.txt_bytes(text), "כל התמלולים.txt", "text/plain; charset=utf-8")
    if format == "docx":
        items = [(r, _speakers(r["id"]), _segments(r["id"])) for r in recs]
        return _download(exporters.to_docx(items), "כל התמלולים.docx",
                         "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    if format == "json":
        data = [exporters.to_json_obj(r, _speakers(r["id"]), _segments(r["id"], with_words=True)) for r in recs]
        return _download(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"), "כל התמלולים.json", "application/json")

    # SRT is per-media by nature: bundle one file per recording.
    buf = io.BytesIO()
    used: set[str] = set()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for r in recs:
            content, name, _ = _export_one(r, "srt")
            base, n = name, 2
            while name in used:
                name = f"{Path(base).stem} ({n}).srt"
                n += 1
            used.add(name)
            z.writestr(name, content)
    return _download(buf.getvalue(), "כל התמלולים - SRT.zip", "application/zip")


# ---------------------------------------------------------------- frontend
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"detail": "Not found"}, status_code=404)
        target = (FRONTEND_DIST / path).resolve()
        if path and target.is_file() and FRONTEND_DIST.resolve() in target.parents:
            return FileResponse(target)
        return FileResponse(FRONTEND_DIST / "index.html")
