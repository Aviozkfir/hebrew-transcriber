import { useRef, useState } from 'react'
import { api, fmtSize, fmtTime, STATUS_LABELS } from './api.js'

export default function Sidebar({ recordings, selectedId, onSelect, onUpload, upload, onTranscribeAll }) {
  const inputRef = useRef()
  const [drag, setDrag] = useState(false)
  const pending = recordings.filter((r) => r.status === 'uploaded' || r.status === 'error').length
  const doneCount = recordings.filter((r) => r.status === 'done').length

  function onDrop(e) {
    e.preventDefault()
    setDrag(false)
    if (upload) return
    onUpload(Array.from(e.dataTransfer.files || []))
  }

  return (
    <aside className="sidebar">
      <div
        className={`dropzone ${drag ? 'drag' : ''} ${upload ? 'busy' : ''}`}
        onClick={() => !upload && inputRef.current.click()}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
      >
        <input
          ref={inputRef}
          type="file"
          multiple
          accept=".mp3,.m4a,.wav,audio/mpeg,audio/mp4,audio/x-m4a,audio/wav"
          hidden
          onChange={(e) => { onUpload(Array.from(e.target.files || [])); e.target.value = '' }}
        />
        {upload ? (
          <>
            <div className="dz-title">מעלה {upload.names.length} קבצים…</div>
            <div className="progress"><div style={{ width: `${Math.round(upload.progress * 100)}%` }} /></div>
            <div className="dz-sub">{Math.round(upload.progress * 100)}%</div>
          </>
        ) : (
          <>
            <div className="dz-icon">⬆</div>
            <div className="dz-title">העלאת הקלטות</div>
            <div className="dz-sub">גררו לכאן או לחצו לבחירה · MP3, M4A, WAV</div>
          </>
        )}
      </div>

      {pending > 1 && (
        <button className="btn primary block" onClick={onTranscribeAll}>
          תמלל את כל הממתינות ({pending})
        </button>
      )}

      <div className="rec-list">
        {recordings.length === 0 && <div className="muted center pad">עדיין לא הועלו הקלטות</div>}
        {recordings.map((r) => (
          <button
            key={r.id}
            className={`rec-item ${r.id === selectedId ? 'active' : ''}`}
            onClick={() => onSelect(r.id)}
            title={r.filename}
          >
            <div className="rec-name" dir="auto">{r.filename}</div>
            <div className="rec-meta">
              <span className={`status s-${r.status}`}>
                {(r.status === 'transcribing' || r.status === 'queued') && <span className="spinner sm" />}
                {STATUS_LABELS[r.status]}
              </span>
              <span className="muted">
                {r.duration_secs ? fmtTime(r.duration_secs) : fmtSize(r.size_bytes)}
              </span>
            </div>
            {(r.name1 || r.name2) && (
              <div className="rec-names muted">{[r.name1, r.name2].filter(Boolean).join(' · ')}</div>
            )}
          </button>
        ))}
      </div>

      {doneCount > 0 && (
        <div className="export-all">
          <div className="section-label">ייצוא כל התמלולים ({doneCount})</div>
          <div className="fmt-row">
            {['docx', 'txt', 'srt', 'json'].map((f) => (
              <a key={f} className="btn small" href={api.exportAllUrl(f)} download>
                {f.toUpperCase()}
              </a>
            ))}
          </div>
          <div className="hint">קובץ משולב אחד · SRT כקובץ ZIP</div>
        </div>
      )}
    </aside>
  )
}
