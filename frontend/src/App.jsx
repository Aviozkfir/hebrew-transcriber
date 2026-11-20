import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import Sidebar from './Sidebar.jsx'
import RecordingView from './RecordingView.jsx'

export default function App() {
  const [recordings, setRecordings] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [health, setHealth] = useState(null)
  const [serverDown, setServerDown] = useState(false)
  const [upload, setUpload] = useState(null) // { names: [], progress }
  const [notice, setNotice] = useState(null)

  const refresh = useCallback(async () => {
    try {
      const list = await api.list()
      setRecordings(list)
      setServerDown(false)
      return list
    } catch {
      setServerDown(true)
      return null
    }
  }, [])

  useEffect(() => {
    refresh()
    api.health().then(setHealth).catch(() => setServerDown(true))
  }, [refresh])

  // Poll faster while something is being transcribed.
  const busy = recordings.some((r) => r.status === 'queued' || r.status === 'transcribing')
  useEffect(() => {
    const t = setInterval(refresh, busy ? 2000 : 10000)
    return () => clearInterval(t)
  }, [busy, refresh])

  useEffect(() => {
    if (selectedId == null && recordings.length) setSelectedId(recordings[0].id)
    if (selectedId != null && recordings.length && !recordings.some((r) => r.id === selectedId)) {
      setSelectedId(recordings[0]?.id ?? null)
    }
  }, [recordings, selectedId])

  const showNotice = useCallback((text, kind = 'error') => {
    setNotice({ text, kind })
  }, [])
  const noticeTimer = useRef()
  useEffect(() => {
    clearTimeout(noticeTimer.current)
    if (notice) noticeTimer.current = setTimeout(() => setNotice(null), 7000)
  }, [notice])

  async function handleUpload(files) {
    const valid = files.filter((f) => /\.(mp3|m4a|wav)$/i.test(f.name))
    const rejected = files.filter((f) => !valid.includes(f))
    if (rejected.length) showNotice(`קבצים שאינם MP3/M4A/WAV לא הועלו: ${rejected.map((f) => f.name).join(', ')}`)
    if (!valid.length) return
    setUpload({ names: valid.map((f) => f.name), progress: 0 })
    try {
      const created = await api.upload(valid, (p) => setUpload((u) => u && { ...u, progress: p }))
      await refresh()
      if (created?.length) setSelectedId(created[0].id)
    } catch (e) {
      showNotice(e.message)
    } finally {
      setUpload(null)
    }
  }

  async function transcribeAllPending() {
    const pending = recordings.filter((r) => r.status === 'uploaded' || r.status === 'error')
    for (const r of pending) {
      try { await api.transcribe(r.id) } catch (e) { showNotice(`${r.filename}: ${e.message}`) }
    }
    refresh()
  }

  const selected = recordings.find((r) => r.id === selectedId) || null

  return (
    <div className="app">
      <header className="topbar">
        <div className="brand">
          <span className="logo">📞</span>
          <div>
            <h1>תמלול שיחות טלפון</h1>
            <div className="sub">תמלול מדויק בעברית · 2–4 דוברים · ElevenLabs Scribe v3</div>
          </div>
        </div>
        {health && !health.api_key_configured && (
          <div className="warn-pill">⚠ לא הוגדר מפתח ElevenLabs בקובץ ‎.env</div>
        )}
      </header>

      {serverDown && <div className="banner error">אין חיבור לשרת המקומי. ודאו שחלון ההפעלה (start.bat) פתוח.</div>}
      {notice && (
        <div className={`banner ${notice.kind}`} onClick={() => setNotice(null)}>
          {notice.text}
        </div>
      )}

      <div className="layout">
        <Sidebar
          recordings={recordings}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onUpload={handleUpload}
          upload={upload}
          onTranscribeAll={transcribeAllPending}
        />
        <main className="main">
          {selected ? (
            <RecordingView
              key={selected.id}
              summary={selected}
              allRecordings={recordings}
              onChanged={refresh}
              onError={showNotice}
            />
          ) : (
            <EmptyState />
          )}
        </main>
      </div>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="empty">
      <div className="empty-icon">🎙️</div>
      <h2>ברוכים הבאים</h2>
      <ol className="steps">
        <li>העלו הקלטה אחת או יותר (MP3, M4A, WAV)</li>
        <li>בחרו את מספר הדוברים בשיחה (2–4) והקלידו את שמותיהם</li>
        <li>לחצו "תמלל"</li>
        <li>בדקו איזה קול שייך לכל שם ואשרו</li>
        <li>תקנו את הטקסט במידת הצורך — כל שינוי נשמר אוטומטית</li>
        <li>ייצאו ל-Word, TXT, SRT או JSON</li>
      </ol>
    </div>
  )
}
