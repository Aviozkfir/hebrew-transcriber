import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, fmtSize, fmtTime, STATUS_LABELS } from './api.js'

const SAVE_DELAY = 700
const SPEAKER_COUNTS = [2, 3, 4]
const NAME_PLACEHOLDERS = ['דני', 'מיכל', 'יוסי', 'רונית']
const colorClass = (n) => `c${((Math.max(1, n || 1) - 1) % 4) + 1}`

export default function RecordingView({ summary, allRecordings, onChanged, onError }) {
  const id = summary.id
  const [detail, setDetail] = useState(null)
  const [names, setNames] = useState({
    name1: summary.name1 || '',
    name2: summary.name2 || '',
    name3: summary.name3 || '',
    name4: summary.name4 || '',
    num_speakers: summary.num_speakers || 2,
  })
  const [saveState, setSaveState] = useState('idle') // idle | saving | saved | error
  const pendingSaves = useRef(0)

  const load = useCallback(async () => {
    try {
      const d = await api.get(id)
      setDetail(d)
    } catch (e) {
      onError(e.message)
    }
  }, [id, onError])

  // Reload full detail on mount and whenever the status changes (e.g. transcription finished).
  useEffect(() => { load() }, [load, summary.status])

  // ---------- autosave helper
  const track = useCallback(async (promise) => {
    pendingSaves.current += 1
    setSaveState('saving')
    try {
      const r = await promise
      pendingSaves.current -= 1
      if (pendingSaves.current === 0) setSaveState('saved')
      return r
    } catch (e) {
      pendingSaves.current -= 1
      setSaveState('error')
      onError(`השמירה נכשלה: ${e.message}`)
      throw e
    }
  }, [onError])

  // ---------- names (debounced autosave)
  const nameTimer = useRef()
  function changeName(key, value) {
    setNames((n) => ({ ...n, [key]: value }))
    clearTimeout(nameTimer.current)
    nameTimer.current = setTimeout(() => {
      track(api.patch(id, { [key]: value })).then(onChanged).catch(() => {})
    }, SAVE_DELAY)
  }
  useEffect(() => () => clearTimeout(nameTimer.current), [])

  async function applyNamesToPending() {
    const targets = allRecordings.filter((r) => r.id !== id && r.status !== 'done')
    await Promise.all(targets.map((r) => track(api.patch(r.id, names)).catch(() => {})))
    onChanged()
  }

  // ---------- actions
  async function transcribe(force = false) {
    if (force && !window.confirm('תמלול מחדש ימחק את כל התיקונים הידניים בהקלטה זו. להמשיך?')) return
    try {
      clearTimeout(nameTimer.current)
      await api.patch(id, names)
      await api.transcribe(id, force)
      onChanged()
    } catch (e) {
      onError(e.message)
    }
  }

  async function remove() {
    if (!window.confirm(`למחוק את "${summary.filename}" ואת התמלול שלה?`)) return
    try {
      await api.remove(id)
      onChanged()
    } catch (e) {
      onError(e.message)
    }
  }

  const status = summary.status
  const rec = detail?.recording
  const transcribed = status === 'done' && detail && detail.segments

  return (
    <div className="rec-view">
      <div className="rec-header">
        <div className="rec-title">
          <h2 dir="auto">{summary.filename}</h2>
          <div className="muted small">
            {fmtSize(summary.size_bytes)}
            {summary.duration_secs ? ` · ${fmtTime(summary.duration_secs)}` : ''}
            {' · '}
            <span className={`status s-${status}`}>{STATUS_LABELS[status]}</span>
          </div>
        </div>
        <div className="rec-actions">
          <SaveIndicator state={saveState} />
          {status === 'done' && (
            <button className="btn ghost small" onClick={() => transcribe(true)} title="שליחה מחדש ל-ElevenLabs">
              תמלול מחדש
            </button>
          )}
          <button className="btn ghost small danger" onClick={remove} disabled={status === 'transcribing'}>
            מחיקה
          </button>
        </div>
      </div>

      <NamesCard
        names={names}
        onChange={changeName}
        detectedCount={status === 'done' ? detail?.speakers?.length : null}
        canApplyToOthers={allRecordings.some((r) => r.id !== id && r.status !== 'done')}
        onApplyToOthers={applyNamesToPending}
      />

      {status !== 'done' && (
        <StatusCard summary={summary} onTranscribe={() => transcribe(false)} names={names} />
      )}

      {transcribed && rec && (
        <Editor
          key={rec.finished_at}
          rec={rec}
          detail={detail}
          setDetail={setDetail}
          names={names}
          track={track}
          onChanged={onChanged}
        />
      )}
    </div>
  )
}

function SaveIndicator({ state }) {
  if (state === 'idle') return null
  const text = { saving: 'שומר…', saved: '✓ כל השינויים נשמרו', error: '⚠ שגיאה בשמירה' }[state]
  return <span className={`save-ind ${state}`}>{text}</span>
}

function NamesCard({ names, onChange, detectedCount, canApplyToOthers, onApplyToOthers }) {
  const count = names.num_speakers
  const slots = Array.from({ length: count }, (_, i) => i + 1)
  return (
    <section className="card">
      <div className="card-title row between">
        <span>שמות הדוברים</span>
        <label className="count-pick">
          מספר דוברים בשיחה:
          <select value={count} onChange={(e) => onChange('num_speakers', Number(e.target.value))}>
            {SPEAKER_COUNTS.map((n) => <option key={n} value={n}>{n}</option>)}
          </select>
        </label>
      </div>
      <div className="names-row">
        {slots.map((slot) => (
          <label key={slot} className="field">
            <span><i className={`dot ${colorClass(slot)}`} /> דובר/ת {slot}</span>
            <input
              value={names[`name${slot}`]}
              placeholder={`לדוגמה: ${NAME_PLACEHOLDERS[slot - 1]}`}
              onChange={(e) => onChange(`name${slot}`, e.target.value)}
            />
          </label>
        ))}
      </div>
      {detectedCount != null && detectedCount !== count && (
        <p className="muted small">
          ההקלטה תומללה עם {detectedCount} דוברים. כדי לזהות {count} דוברים לחצו "תמלול מחדש".
        </p>
      )}
      {canApplyToOthers && slots.some((s) => names[`name${s}`]) && (
        <button className="link-btn" onClick={onApplyToOthers}>
          החל את מספר הדוברים והשמות על כל ההקלטות שטרם תומללו
        </button>
      )}
    </section>
  )
}

function useElapsed(startIso, active) {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    if (!active) return
    const t = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(t)
  }, [active])
  if (!startIso) return 0
  return Math.max(0, (now - new Date(startIso).getTime()) / 1000)
}

function StatusCard({ summary, onTranscribe, names }) {
  const { status } = summary
  const elapsed = useElapsed(summary.started_at, status === 'transcribing')
  const missingNames = Array.from({ length: names.num_speakers }, (_, i) => names[`name${i + 1}`])
    .some((n) => !n.trim())

  if (status === 'uploaded') {
    return (
      <section className="card status-card">
        <p>הקובץ הועלה ומוכן לתמלול. ההקלטה כולה תישלח ל-ElevenLabs כקובץ אחד.</p>
        <p className="muted small">
          ElevenLabs יזהה {names.num_speakers} קולות שונים. ודאו שמספר הדוברים שנבחר למעלה נכון לפני התמלול.
        </p>
        {missingNames && <p className="muted small">מומלץ להזין את שמות כל הדוברים לפני התמלול (ניתן גם אחר כך).</p>}
        <button className="btn primary big" onClick={onTranscribe}>תמלל</button>
      </section>
    )
  }
  if (status === 'queued') {
    return (
      <section className="card status-card">
        <div className="row"><span className="spinner" /> <b>ממתין בתור לתמלול…</b></div>
        <div className="progress indeterminate"><div /></div>
      </section>
    )
  }
  if (status === 'transcribing') {
    return (
      <section className="card status-card">
        <div className="row"><span className="spinner" /> <b>מתמלל באמצעות ElevenLabs…</b></div>
        <div className="progress indeterminate"><div /></div>
        <p className="muted small">
          זמן שחלף: {fmtTime(elapsed)} · שיחה של כ-40 דקות מתומללת בדרך כלל בתוך מספר דקות.
          אפשר להמשיך לעבוד על הקלטות אחרות בינתיים.
        </p>
      </section>
    )
  }
  if (status === 'error') {
    return (
      <section className="card status-card error">
        <b>התמלול נכשל</b>
        <p className="err-text">{summary.error}</p>
        <button className="btn primary" onClick={onTranscribe}>נסה שוב</button>
      </section>
    )
  }
  return null
}

// =====================================================================
// Editor: speakers, player, transcript, export
// =====================================================================
function Editor({ rec, detail, setDetail, names, track, onChanged }) {
  const { speakers, segments } = detail
  const audioRef = useRef()
  const [time, setTime] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [follow, setFollow] = useState(true)
  const [rate, setRate] = useState(1)
  const stopAtRef = useRef(null)

  const confirmed = !!rec.speakers_confirmed
  const slotOf = useMemo(() => Object.fromEntries(speakers.map((s) => [s.speaker_id, s.slot])), [speakers])
  const labelOf = useMemo(() => Object.fromEntries(speakers.map((s) => [s.speaker_id, s.label_index])), [speakers])

  const nameForSlot = useCallback(
    (slot) => (names[`name${slot}`] || '').trim() || `דובר ${slot}`,
    [names],
  )
  // Name choices offered for each voice: the expected speakers, plus any slot already in use.
  const numSlots = Math.max(names.num_speakers, ...speakers.map((s) => s.slot))
  // Before the user confirms the voice→name mapping, show the neutral detected labels.
  const display = useCallback(
    (speakerId) => {
      if (!confirmed) return { text: `דובר ${labelOf[speakerId] ?? '?'}`, color: labelOf[speakerId] ?? 1 }
      const slot = slotOf[speakerId] ?? 1
      return { text: nameForSlot(slot), color: slot }
    },
    [confirmed, labelOf, slotOf, nameForSlot],
  )

  // ---------- audio time tracking (smooth while playing)
  useEffect(() => {
    if (!playing) return
    let raf
    const tick = () => {
      const a = audioRef.current
      if (a) {
        setTime(a.currentTime)
        if (stopAtRef.current != null && a.currentTime >= stopAtRef.current) {
          a.pause()
          stopAtRef.current = null
        }
      }
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  useEffect(() => { if (audioRef.current) audioRef.current.playbackRate = rate }, [rate])

  const seek = useCallback((t, { play = false, stopAt = null } = {}) => {
    const a = audioRef.current
    if (!a) return
    a.currentTime = Math.max(0, t)
    setTime(a.currentTime)
    stopAtRef.current = stopAt
    if (play) a.play().catch(() => {})
  }, [])

  // ---------- active segment (binary search on start times)
  const activeIdx = useMemo(() => {
    let lo = 0, hi = segments.length - 1, ans = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      if (segments[mid].start <= time + 0.05) { ans = mid; lo = mid + 1 } else hi = mid - 1
    }
    if (ans >= 0) {
      const seg = segments[ans]
      const next = segments[ans + 1]
      // Between segments (silence) keep the previous one highlighted only briefly.
      if (time > seg.end + 1.5 && (!next || time < next.start)) return -1
    }
    return ans
  }, [segments, time])

  const listRef = useRef()
  useEffect(() => {
    if (!follow || activeIdx < 0 || !playing) return
    const ae = document.activeElement
    if (ae && ae.tagName === 'TEXTAREA' && listRef.current?.contains(ae)) return // don't jump while editing
    const el = listRef.current?.querySelector(`[data-idx="${activeIdx}"]`)
    el?.scrollIntoView({ block: 'center', behavior: 'smooth' })
  }, [activeIdx, follow, playing])

  // ---------- segment edits (debounced autosave per segment)
  const timers = useRef({})
  const updateLocal = useCallback((segId, patch) => {
    setDetail((d) => ({ ...d, segments: d.segments.map((s) => (s.id === segId ? { ...s, ...patch } : s)) }))
  }, [setDetail])

  const onText = useCallback((segId, text) => {
    updateLocal(segId, { text })
    clearTimeout(timers.current[segId]?.t)
    timers.current[segId] = {
      text,
      t: setTimeout(() => {
        delete timers.current[segId]
        track(api.patchSegment(segId, { text })).catch(() => {})
      }, SAVE_DELAY),
    }
  }, [updateLocal, track])

  // Flush pending text saves when leaving the recording or closing the window.
  useEffect(() => {
    const flush = () => {
      for (const [segId, { t, text }] of Object.entries(timers.current)) {
        clearTimeout(t)
        fetch(`/api/segments/${segId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
          keepalive: true,
        })
      }
      timers.current = {}
    }
    window.addEventListener('beforeunload', flush)
    return () => { window.removeEventListener('beforeunload', flush); flush() }
  }, [])

  const onSpeaker = useCallback((segId, speakerId) => {
    updateLocal(segId, { speaker_id: speakerId })
    track(api.patchSegment(segId, { speaker_id: speakerId })).catch(() => {})
  }, [updateLocal, track])

  const onRevert = useCallback(async (segId) => {
    clearTimeout(timers.current[segId]?.t)
    delete timers.current[segId]
    try {
      const seg = await track(api.revertSegment(segId))
      updateLocal(segId, { text: seg.text, speaker_id: seg.speaker_id })
    } catch { /* reported */ }
  }, [track, updateLocal])

  // ---------- speaker mapping
  async function saveMapping(mapping, confirm) {
    try {
      const r = await track(api.setSpeakers(rec.id, mapping, confirm))
      setDetail((d) => ({ ...d, speakers: r.speakers, recording: { ...d.recording, ...r.recording } }))
      onChanged()
    } catch { /* reported */ }
  }

  const editedCount = segments.filter((s) => s.text !== s.original_text || s.speaker_id !== s.original_speaker_id).length

  return (
    <>
      <SpeakerCard
        speakers={speakers}
        segments={segments}
        confirmed={confirmed}
        nameForSlot={nameForSlot}
        numSlots={numSlots}
        onSave={saveMapping}
        onPlaySample={(seg) => seek(seg.start, { play: true, stopAt: Math.min(seg.end + 0.3, seg.start + 15) })}
      />

      <div className="player-bar">
        <audio
          ref={audioRef}
          src={api.audioUrl(rec.id)}
          controls
          preload="metadata"
          onPlay={() => setPlaying(true)}
          onPause={() => { setPlaying(false); setTime(audioRef.current.currentTime) }}
          onSeeked={() => setTime(audioRef.current.currentTime)}
          onLoadedMetadata={() => { audioRef.current.playbackRate = rate }}
        />
        <div className="player-tools">
          <select value={rate} onChange={(e) => setRate(Number(e.target.value))} title="מהירות ניגון">
            {[0.75, 1, 1.25, 1.5, 1.75, 2].map((r) => <option key={r} value={r}>×{r}</option>)}
          </select>
          <label className="check">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            גלילה אוטומטית
          </label>
        </div>
      </div>

      <section className="card transcript-card">
        <div className="transcript-head">
          <div className="card-title">
            תמלול <span className="muted small">· {segments.length} משפטים{editedCount ? ` · ${editedCount} תוקנו` : ''}</span>
          </div>
          <ExportBar recId={rec.id} />
        </div>
        <div className="hint">לחיצה על משפט מעבירה את הנגן לנקודה זו. ניתן לערוך את הטקסט ולשנות דובר לכל משפט — השינויים נשמרים אוטומטית.</div>
        <div className="transcript" ref={listRef}>
          {segments.map((seg, i) => (
            <SegmentRow
              key={seg.id}
              idx={i}
              seg={seg}
              active={i === activeIdx}
              speakers={speakers}
              display={display}
              onSeek={seek}
              onText={onText}
              onSpeaker={onSpeaker}
              onRevert={onRevert}
            />
          ))}
        </div>
      </section>
    </>
  )
}

function SpeakerCard({ speakers, segments, confirmed, nameForSlot, numSlots, onSave, onPlaySample }) {
  const samples = useMemo(() => {
    const out = {}
    for (const sp of speakers) {
      const own = segments.filter((s) => s.original_speaker_id === sp.speaker_id)
      const long = own.filter((s) => s.text.length > 25)
      out[sp.speaker_id] = { seg: long[0] || own[0], count: own.length, preview: (long.length ? long : own).slice(0, 2) }
    }
    return out
  }, [speakers, segments])

  const mapping = Object.fromEntries(speakers.map((s) => [s.speaker_id, s.slot]))

  function setSlot(speakerId, slot) {
    // Give the chosen name to this voice; the voice that had it takes this voice's old name.
    const m = { ...mapping, [speakerId]: slot }
    const holder = speakers.find((s) => s.speaker_id !== speakerId && mapping[s.speaker_id] === slot)
    if (holder) m[holder.speaker_id] = mapping[speakerId]
    onSave(m, confirmed ? true : undefined)
  }

  function swap() {
    const m = Object.fromEntries(speakers.map((s) => [s.speaker_id, s.slot === 1 ? 2 : 1]))
    onSave(m, confirmed ? true : undefined)
  }

  return (
    <section className={`card speaker-card ${confirmed ? 'ok' : 'attention'}`}>
      <div className="card-title row between">
        <span>זיהוי דוברים</span>
        {confirmed ? <span className="badge ok">✓ השיוך אושר</span> : <span className="badge warn">נדרש אישור</span>}
      </div>
      {!confirmed && (
        <p className="small">האזינו לדוגמה מכל קול ובחרו לאיזה שם הוא שייך, ואז לחצו "אישור שיוך".</p>
      )}
      <div className="speaker-grid">
        {speakers.map((sp) => {
          const s = samples[sp.speaker_id]
          return (
            <div key={sp.speaker_id} className="speaker-box">
              <div className="row between">
                <b><i className={`dot ${colorClass(sp.label_index)}`} /> דובר {sp.label_index}</b>
                <span className="muted small">{s.count} משפטים</span>
              </div>
              {s.seg ? (
                <button className="sample" onClick={() => onPlaySample(s.seg)} title="השמעת דוגמה">
                  <span className="play">▶</span>
                  <span className="sample-text">{s.preview.map((p) => p.text).join(' … ')}</span>
                </button>
              ) : (
                <div className="muted small">לא זוהה דיבור לקול זה</div>
              )}
              <div className="assign">
                <span>זהו/זוהי:</span>
                <div className="seg-toggle">
                  {Array.from({ length: numSlots }, (_, i) => i + 1).map((slot) => (
                    <button
                      key={slot}
                      className={`${sp.slot === slot ? `on ${colorClass(slot)}` : ''}`}
                      onClick={() => setSlot(sp.speaker_id, slot)}
                    >
                      {nameForSlot(slot)}
                    </button>
                  ))}
                </div>
              </div>
            </div>
          )
        })}
      </div>
      <div className="row gap">
        {speakers.length === 2 && <button className="btn ghost small" onClick={swap}>⇄ החלף בין הדוברים</button>}
        {!confirmed && <button className="btn primary" onClick={() => onSave(mapping, true)}>אישור שיוך</button>}
        {confirmed && <button className="link-btn" onClick={() => onSave(mapping, false)}>הצג שוב כ"דובר 1, דובר 2…"</button>}
      </div>
    </section>
  )
}

const SegmentRow = memo(function SegmentRow({ idx, seg, active, speakers, display, onSeek, onText, onSpeaker, onRevert }) {
  const taRef = useRef()
  const d = display(seg.speaker_id)
  const edited = seg.text !== seg.original_text || seg.speaker_id !== seg.original_speaker_id

  useEffect(() => {
    const ta = taRef.current
    if (ta) { ta.style.height = 'auto'; ta.style.height = `${ta.scrollHeight}px` }
  }, [seg.text])

  return (
    <div
      className={`seg ${active ? 'active' : ''} ${edited ? 'edited' : ''}`}
      data-idx={idx}
      onClick={() => onSeek(seg.start)}
    >
      <button className="ts" onClick={(e) => { e.stopPropagation(); onSeek(seg.start, { play: true }) }} title="נגן מכאן">
        [{fmtTime(seg.start)}]
      </button>
      <select
        className={`spk ${colorClass(d.color)}`}
        value={seg.speaker_id}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => onSpeaker(seg.id, e.target.value)}
        title="שינוי דובר למשפט זה"
      >
        {speakers.map((sp) => (
          <option key={sp.speaker_id} value={sp.speaker_id}>{display(sp.speaker_id).text}</option>
        ))}
      </select>
      <textarea
        ref={taRef}
        dir="rtl"
        rows={1}
        value={seg.text}
        spellCheck={false}
        onChange={(e) => onText(seg.id, e.target.value)}
      />
      {edited && (
        <button
          className="revert"
          title={`שחזור הטקסט והדובר המקוריים:\n${seg.original_text}`}
          onClick={(e) => { e.stopPropagation(); onRevert(seg.id) }}
        >
          ↺
        </button>
      )}
    </div>
  )
})

function ExportBar({ recId }) {
  return (
    <div className="export-bar">
      <span className="muted small">הורדה:</span>
      {['docx', 'txt', 'srt', 'json'].map((f) => (
        <a key={f} className="btn small" href={api.exportUrl(recId, f)} download>{f.toUpperCase()}</a>
      ))}
      <a className="btn small ghost" href={api.rawUrl(recId)} download title="תשובת ה-API המקורית והמלאה מ-ElevenLabs">
        API מקורי
      </a>
    </div>
  )
}
