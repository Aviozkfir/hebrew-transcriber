"""Turn ElevenLabs word-level output into sentence-level transcript segments.

No text is altered: segment text is the exact concatenation of the word and
spacing tokens returned by the API. Only non-speech audio events are dropped.
"""
import re

# Sentence end: ?, ! or a single period. Ellipses ("..." / "…") mark hesitation, not a sentence end.
SENTENCE_END = re.compile(r"(?:[?!]+|(?<!\.)\.)[\"'”״)]*$")
EVENT_LIKE = re.compile(r"^\s*[\(\[][^\)\]]*[\)\]]\s*$")  # e.g. "(laughter)"
PAUSE_SPLIT_SECS = 1.5
MAX_SEGMENT_SECS = 30.0
# Very short utterances ("הלו? מיכל?") stay together with what follows from the same speaker.
MIN_WORDS_FOR_SENTENCE_SPLIT = 3
DEFAULT_SPEAKER = "speaker_0"


def _is_speech(token: dict) -> bool:
    ttype = token.get("type")
    if ttype == "audio_event":
        return False
    if ttype == "word" and EVENT_LIKE.match(token.get("text") or ""):
        return False
    return True


def build_segments(response: dict) -> tuple[list[dict], list[str]]:
    """Return (segments, speaker_ids in order of first appearance)."""
    tokens = [t for t in (response.get("words") or []) if _is_speech(t)]

    segments: list[dict] = []
    current: dict | None = None
    speaker_order: list[str] = []
    prev_word: dict | None = None
    pending_spacing: list[dict] = []

    def close():
        nonlocal current
        if current and current["word_count"] > 0:
            current["text"] = "".join(t.get("text") or "" for t in current["tokens"]).strip()
            if current["text"]:
                segments.append(current)
        current = None

    for tok in tokens:
        if tok.get("type") == "spacing":
            pending_spacing.append(tok)
            continue

        speaker = tok.get("speaker_id") or (prev_word or {}).get("speaker_id") or DEFAULT_SPEAKER
        if speaker not in speaker_order:
            speaker_order.append(speaker)
        start = tok.get("start")
        end = tok.get("end")
        if start is None:
            start = (prev_word or {}).get("end") or 0.0
        if end is None:
            end = start

        new_segment = current is None
        if current is not None:
            prev_text = (prev_word or {}).get("text") or ""
            gap = start - (current["end"] or start)
            if speaker != current["speaker_id"]:
                new_segment = True
            elif current["word_count"] >= MIN_WORDS_FOR_SENTENCE_SPLIT and SENTENCE_END.search(prev_text.strip()):
                new_segment = True
            elif gap > PAUSE_SPLIT_SECS:
                new_segment = True
            elif current["end"] - current["start"] > MAX_SEGMENT_SECS:
                new_segment = True

        if new_segment:
            close()
            pending_spacing = []  # spacing between segments is not part of either
            current = {"start": start, "end": end, "speaker_id": speaker, "tokens": [], "word_count": 0}
        else:
            current["tokens"].extend(pending_spacing)
            pending_spacing = []

        current["tokens"].append(tok)
        current["word_count"] += 1
        current["end"] = max(current["end"], end)
        prev_word = {**tok, "speaker_id": speaker}

    close()

    for s in segments:
        s.pop("word_count", None)
    return segments, speaker_order
