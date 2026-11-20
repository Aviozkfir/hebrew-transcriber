"""Estimate how high each detected voice is (median fundamental frequency, in Hz).

Used only to suggest which voice belongs to the woman in the call: women's voices
are usually clearly higher (about 165-255 Hz) than men's (about 85-155 Hz).
The audio is decoded locally with PyAV; nothing is sent anywhere.
"""
import logging
from pathlib import Path

import numpy as np

log = logging.getLogger("pitch")

SAMPLE_RATE = 8000           # enough for voice pitch, and keeps memory low for long calls
FRAME = 400                  # 50 ms analysis window
HOP = 160                    # 20 ms step
MIN_F0, MAX_F0 = 70.0, 400.0
VOICING_THRESHOLD = 0.45     # normalized autocorrelation peak needed to count a frame as voiced
MAX_SECONDS_PER_SPEAKER = 90.0
MIN_SEGMENT_SECONDS = 0.6


def _pick_windows(segments: list[dict]) -> dict[str, list[tuple[float, float]]]:
    """Choose up to MAX_SECONDS_PER_SPEAKER of each voice's own (unedited) sentences, longest first."""
    by_speaker: dict[str, list[tuple[float, float]]] = {}
    for s in segments:
        start, end = float(s["start"]), float(s["end"])
        if end - start >= MIN_SEGMENT_SECONDS:
            by_speaker.setdefault(s["speaker_id"], []).append((start, end))
    out = {}
    for sp, wins in by_speaker.items():
        wins.sort(key=lambda w: w[1] - w[0], reverse=True)
        chosen, total = [], 0.0
        for w in wins:
            if total >= MAX_SECONDS_PER_SPEAKER:
                break
            chosen.append(w)
            total += w[1] - w[0]
        out[sp] = sorted(chosen)
    return out


def _decode_windows(path: Path, windows: list[tuple[float, float, str]]) -> dict[str, list[np.ndarray]]:
    """Stream-decode the file to mono 8 kHz and keep only the samples inside the windows.

    Returns, per speaker, one continuous array per window (sentence).
    """
    import av  # imported lazily so the app still starts if PyAV is missing

    windows = sorted(windows)
    pieces: dict[tuple, list[np.ndarray]] = {}  # (start, end, speaker) -> decoded chunks
    pos = 0  # samples emitted so far
    with av.open(str(path)) as container:
        stream = container.streams.audio[0]
        resampler = av.AudioResampler(format="s16", layout="mono", rate=SAMPLE_RATE)
        last_end = int(max(w[1] for w in windows) * SAMPLE_RATE) + 1

        def take(frames):
            nonlocal pos
            for fr in frames:
                data = fr.to_ndarray().reshape(-1).astype(np.float32) / 32768.0
                a, b = pos, pos + len(data)
                for w in windows:
                    s, e = max(a, int(w[0] * SAMPLE_RATE)), min(b, int(w[1] * SAMPLE_RATE))
                    if e > s:
                        pieces.setdefault(w, []).append(data[s - a:e - a])
                pos = b

        for frame in container.decode(stream):
            take(resampler.resample(frame))
            if pos > last_end:
                break
        else:
            take(resampler.resample(None))  # flush
    out: dict[str, list[np.ndarray]] = {}
    for (_, _, sp), chunks in pieces.items():
        out.setdefault(sp, []).append(np.concatenate(chunks))
    return out


def _f0_frames(x: np.ndarray) -> np.ndarray:
    """Per-frame F0 estimates (Hz) for voiced frames, by normalized autocorrelation."""
    if len(x) < FRAME:
        return np.empty(0)
    n = 1 + (len(x) - FRAME) // HOP
    idx = np.arange(FRAME)[None, :] + HOP * np.arange(n)[:, None]
    frames = x[idx]
    frames = frames - frames.mean(axis=1, keepdims=True)
    energy = (frames ** 2).mean(axis=1)
    loud = energy > max(1e-6, np.percentile(energy, 30))  # skip quiet frames
    frames = frames[loud] * np.hanning(FRAME)
    if not len(frames):
        return np.empty(0)
    spec = np.fft.rfft(frames, 2 * FRAME, axis=1)
    ac = np.fft.irfft(np.abs(spec) ** 2, axis=1)[:, :FRAME]
    ac = ac / np.maximum(ac[:, :1], 1e-12)
    lo, hi = int(SAMPLE_RATE / MAX_F0), int(SAMPLE_RATE / MIN_F0)
    band = ac[:, lo:hi + 1]
    lag = band.argmax(axis=1) + lo
    peak = band.max(axis=1)
    voiced = peak > VOICING_THRESHOLD
    return SAMPLE_RATE / lag[voiced]


def speaker_pitches(audio_path: Path, segments: list[dict]) -> dict[str, float]:
    """Median voice pitch (Hz) per speaker_id. Returns {} if the audio can't be analysed."""
    try:
        chosen = _pick_windows(segments)
        flat = [(s, e, sp) for sp, wins in chosen.items() for s, e in wins]
        if not flat:
            return {}
        pieces = _decode_windows(audio_path, flat)
        out = {}
        for sp, chunks in pieces.items():
            f0 = np.concatenate([_f0_frames(c) for c in chunks]) if chunks else np.empty(0)
            if len(f0) >= 20:  # need some voiced speech to be meaningful
                out[sp] = round(float(np.median(f0)), 1)
        return out
    except Exception:  # never let pitch analysis break a transcription
        log.exception("Voice pitch analysis failed for %s", audio_path)
        return {}


def assign_slots(speaker_order: list[str], num_speakers: int, female_slot: int | None,
                 pitches: dict[str, float]) -> dict[str, int]:
    """Map detected voices to name slots.

    Names are filled in the order people first speak. If one name is marked as the
    woman (female_slot), the highest-pitched voice gets that name and the other voices
    take the remaining names, still in speaking order.
    """
    slots = list(range(1, num_speakers + 1))
    female_voice = None
    if female_slot in slots and len(pitches) >= 2:
        female_voice = max(pitches, key=pitches.get)
    rest_slots = [s for s in slots if s != female_slot] if female_voice else slots
    out, i = {}, 0
    for sp in speaker_order:
        if sp == female_voice:
            out[sp] = female_slot
        else:
            out[sp] = rest_slots[i % len(rest_slots)] if rest_slots else 1
            i += 1
    return out
