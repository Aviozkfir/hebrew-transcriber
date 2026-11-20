"""SQLite persistence."""
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from .config import DB_PATH

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    filename        TEXT NOT NULL,
    stored_name     TEXT NOT NULL,
    size_bytes      INTEGER NOT NULL DEFAULT 0,
    name1           TEXT NOT NULL DEFAULT '',
    name2           TEXT NOT NULL DEFAULT '',
    name3           TEXT NOT NULL DEFAULT '',
    name4           TEXT NOT NULL DEFAULT '',
    num_speakers    INTEGER NOT NULL DEFAULT 2,       -- expected number of people in the call (2-4)
    female_slot     INTEGER NOT NULL DEFAULT 0,       -- which name (1-4) is the woman; 0 = none marked
    status          TEXT NOT NULL DEFAULT 'uploaded',  -- uploaded|queued|transcribing|done|error
    error           TEXT,
    started_at      TEXT,
    finished_at     TEXT,
    duration_secs   REAL,
    language_code   TEXT,
    response_file   TEXT,
    speakers_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- Detected (diarized) speakers per recording and which entered name they map to.
CREATE TABLE IF NOT EXISTS speakers (
    recording_id    INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    speaker_id      TEXT NOT NULL,      -- as returned by ElevenLabs, e.g. speaker_0
    label_index     INTEGER NOT NULL,   -- 1-based order of first appearance ("Speaker 1")
    slot            INTEGER NOT NULL,   -- 1 => name1, 2 => name2, 3 => name3, 4 => name4
    pitch_hz        REAL,               -- median voice pitch, used to recognise the woman's voice
    PRIMARY KEY (recording_id, speaker_id)
);

CREATE TABLE IF NOT EXISTS segments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    recording_id        INTEGER NOT NULL REFERENCES recordings(id) ON DELETE CASCADE,
    idx                 INTEGER NOT NULL,
    start               REAL NOT NULL,
    end                 REAL NOT NULL,
    speaker_id          TEXT NOT NULL,
    original_speaker_id TEXT NOT NULL,
    text                TEXT NOT NULL,
    original_text       TEXT NOT NULL,
    words_json          TEXT NOT NULL,
    updated_at          TEXT
);
CREATE INDEX IF NOT EXISTS ix_segments_rec ON segments(recording_id, idx);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


_conn = _connect()


@contextmanager
def tx():
    """Serialized transaction on the shared connection."""
    with _lock:
        try:
            yield _conn
            _conn.commit()
        except Exception:
            _conn.rollback()
            raise


# Columns added after the first release; added to existing databases on startup.
MIGRATIONS = {
    "recordings": {
        "name3": "TEXT NOT NULL DEFAULT ''",
        "name4": "TEXT NOT NULL DEFAULT ''",
        "num_speakers": "INTEGER NOT NULL DEFAULT 2",
        "female_slot": "INTEGER NOT NULL DEFAULT 0",
    },
    "speakers": {
        "pitch_hz": "REAL",
    },
}


def init_db() -> None:
    with tx() as c:
        c.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            existing = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in existing:
                    c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")


def query(sql: str, params=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in _conn.execute(sql, params).fetchall()]


def query_one(sql: str, params=()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None
