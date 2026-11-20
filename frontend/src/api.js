async function request(method, url, body) {
  const res = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    let msg = `שגיאה ${res.status}`
    try {
      const data = await res.json()
      if (data.detail) msg = typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)
    } catch { /* not JSON */ }
    throw new Error(msg)
  }
  return res.json()
}

export const api = {
  health: () => request('GET', '/api/health'),
  list: () => request('GET', '/api/recordings'),
  get: (id) => request('GET', `/api/recordings/${id}`),
  patch: (id, body) => request('PATCH', `/api/recordings/${id}`, body),
  remove: (id) => request('DELETE', `/api/recordings/${id}`),
  transcribe: (id, force = false) => request('POST', `/api/recordings/${id}/transcribe${force ? '?force=true' : ''}`),
  setSpeakers: (id, mapping, confirmed) => request('PUT', `/api/recordings/${id}/speakers`, { mapping, confirmed }),
  patchSegment: (id, body) => request('PATCH', `/api/segments/${id}`, body),
  revertSegment: (id) => request('POST', `/api/segments/${id}/revert`),
  audioUrl: (id) => `/api/recordings/${id}/audio`,
  rawUrl: (id) => `/api/recordings/${id}/raw`,
  exportUrl: (id, fmt) => `/api/recordings/${id}/export?format=${fmt}`,
  exportAllUrl: (fmt) => `/api/export?format=${fmt}`,

  /** Upload with progress reporting (fetch has no upload progress). */
  upload(files, onProgress) {
    return new Promise((resolve, reject) => {
      const form = new FormData()
      for (const f of files) form.append('files', f, f.name)
      const xhr = new XMLHttpRequest()
      xhr.open('POST', '/api/recordings')
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
      xhr.onload = () => {
        let data = null
        try { data = JSON.parse(xhr.responseText) } catch { /* ignore */ }
        if (xhr.status >= 200 && xhr.status < 300) resolve(data)
        else reject(new Error(data?.detail || `ההעלאה נכשלה (${xhr.status})`))
      }
      xhr.onerror = () => reject(new Error('ההעלאה נכשלה: אין חיבור לשרת המקומי'))
      xhr.send(form)
    })
  },
}

export function fmtTime(sec) {
  const s = Math.max(0, Math.floor(sec || 0))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = s % 60
  return [h, m, ss].map((n) => String(n).padStart(2, '0')).join(':')
}

export function fmtSize(bytes) {
  if (!bytes) return ''
  if (bytes > 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${Math.round(bytes / 1024)} KB`
}

export const STATUS_LABELS = {
  uploaded: 'ממתין לתמלול',
  queued: 'בתור',
  transcribing: 'מתמלל…',
  done: 'תומלל',
  error: 'שגיאה',
}
