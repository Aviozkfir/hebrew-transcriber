"""Transcript export: TXT, DOCX, SRT, JSON — with real speaker names and Hebrew RTL formatting."""
import io
import json
from datetime import datetime
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

RLM = "‏"  # Right-to-left mark: makes bidi-aware viewers lay out each line RTL.


def fmt_ts(seconds: float) -> str:
    s = int(seconds or 0)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d}"


def fmt_srt_ts(seconds: float) -> str:
    ms = int(round((seconds or 0) * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def speaker_name_map(rec: dict, speakers: list[dict]) -> dict[str, str]:
    names = {1: (rec.get("name1") or "").strip(), 2: (rec.get("name2") or "").strip()}
    out = {}
    for sp in speakers:
        out[sp["speaker_id"]] = names.get(sp["slot"]) or f"דובר {sp['slot']}"
    return out


def _lines(rec, speakers, segments):
    names = speaker_name_map(rec, speakers)
    for seg in sorted(segments, key=lambda s: (s["start"], s["idx"])):
        yield seg, names.get(seg["speaker_id"], seg["speaker_id"])


def _title(rec) -> str:
    # Without the extension: "שיחה 1.wav" would be reordered by the bidi algorithm.
    return Path(rec["filename"]).stem or rec["filename"]


def _participants(rec) -> str:
    n = [x for x in ((rec.get("name1") or "").strip(), (rec.get("name2") or "").strip()) if x]
    return " ו".join(n) if len(n) == 2 else (n[0] if n else "")


# ---------- TXT ----------
def to_txt(rec, speakers, segments) -> str:
    out = [f"{RLM}תמלול: {_title(rec)}"]
    if _participants(rec):
        out.append(f"{RLM}משתתפים: {_participants(rec)}")
    if rec.get("duration_secs"):
        out.append(f"{RLM}משך: {fmt_ts(rec['duration_secs'])}")
    out.append("")
    for seg, name in _lines(rec, speakers, segments):
        out.append(f"{RLM}[{fmt_ts(seg['start'])}] {name}: {seg['text']}")
        out.append("")
    return "\r\n".join(out)


def txt_bytes(text: str) -> bytes:
    return "﻿".encode("utf-8") + text.encode("utf-8")  # BOM so Windows apps detect UTF-8


# ---------- SRT ----------
def to_srt(rec, speakers, segments) -> str:
    out = []
    for i, (seg, name) in enumerate(_lines(rec, speakers, segments), start=1):
        end = seg["end"] if seg["end"] > seg["start"] else seg["start"] + 1
        out.append(str(i))
        out.append(f"{fmt_srt_ts(seg['start'])} --> {fmt_srt_ts(end)}")
        out.append(f"{RLM}{name}: {seg['text']}")
        out.append("")
    return "\r\n".join(out)


# ---------- JSON ----------
def to_json_obj(rec, speakers, segments) -> dict:
    names = speaker_name_map(rec, speakers)
    return {
        "file": rec["filename"],
        "duration_secs": rec.get("duration_secs"),
        "language_code": rec.get("language_code"),
        "speakers": [
            {
                "speaker_id": sp["speaker_id"],
                "detected_label": f"Speaker {sp['label_index']}",
                "name": names[sp["speaker_id"]],
            }
            for sp in speakers
        ],
        "segments": [
            {
                "index": i,
                "start": seg["start"],
                "end": seg["end"],
                "timestamp": fmt_ts(seg["start"]),
                "speaker_id": seg["speaker_id"],
                "speaker": name,
                "text": seg["text"],
                "original_text": seg["original_text"],
                "original_speaker_id": seg["original_speaker_id"],
                "edited": seg["text"] != seg["original_text"] or seg["speaker_id"] != seg["original_speaker_id"],
                "words": json.loads(seg["words_json"]),
            }
            for i, (seg, name) in enumerate(_lines(rec, speakers, segments))
        ],
    }


# ---------- DOCX ----------
def _set_rtl_paragraph(p):
    ppr = p._p.get_or_add_pPr()
    bidi = OxmlElement("w:bidi")
    bidi.set(qn("w:val"), "1")
    ppr.insert(0, bidi)
    # No explicit <w:jc>: in a bidi paragraph Word treats "right" as "end" (= left).
    # The default alignment of an RTL paragraph is already its right edge.


def _rtl_run(p, text, bold=False, size=12, color=None):
    run = p.add_run(text)
    font = run.font
    font.name = "David"
    font.size = Pt(size)
    font.bold = bold
    font.cs_bold = bold
    font.rtl = True
    if color:
        font.color.rgb = RGBColor.from_string(color)
    rpr = run._r.get_or_add_rPr()
    rpr.get_or_add_rFonts().set(qn("w:cs"), "David")
    szcs = OxmlElement("w:szCs")  # complex-script (Hebrew) font size; must follow <w:sz>
    szcs.set(qn("w:val"), str(size * 2))
    rpr.sz.addnext(szcs)
    return run


def _add_recording_to_doc(doc, rec, speakers, segments, heading_level=1):
    h = doc.add_paragraph()
    _set_rtl_paragraph(h)
    _rtl_run(h, f"תמלול: {_title(rec)}", bold=True, size=16 if heading_level == 1 else 14)
    meta = []
    if _participants(rec):
        meta.append(f"משתתפים: {_participants(rec)}")
    if rec.get("duration_secs"):
        meta.append(f"משך: {fmt_ts(rec['duration_secs'])}")
    if meta:
        p = doc.add_paragraph()
        _set_rtl_paragraph(p)
        _rtl_run(p, "   |   ".join(meta), size=10, color="666666")

    for seg, name in _lines(rec, speakers, segments):
        p = doc.add_paragraph()
        _set_rtl_paragraph(p)
        p.paragraph_format.space_after = Pt(6)
        _rtl_run(p, f"[{fmt_ts(seg['start'])}] ", size=10, color="888888")
        _rtl_run(p, f"{name}: ", bold=True)
        _rtl_run(p, seg["text"])


def _new_doc():
    doc = Document()
    sect = doc.sections[0]
    sect_pr = sect._sectPr
    bidi = OxmlElement("w:bidi")
    grid = sect_pr.find(qn("w:docGrid"))
    if grid is not None:
        grid.addprevious(bidi)
    else:
        sect_pr.append(bidi)
    style = doc.styles["Normal"]
    style.font.name = "David"
    style.font.size = Pt(12)
    return doc


def to_docx(items: list[tuple[dict, list, list]]) -> bytes:
    doc = _new_doc()
    for i, (rec, speakers, segments) in enumerate(items):
        if i > 0:
            doc.add_page_break()
        _add_recording_to_doc(doc, rec, speakers, segments)
    foot = doc.add_paragraph()
    _set_rtl_paragraph(foot)
    _rtl_run(foot, f"הופק בתאריך {datetime.now():%d/%m/%Y %H:%M}", size=8, color="999999")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()
