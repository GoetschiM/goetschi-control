import { useEffect, useRef, useState } from 'react'

// Single fetch helper. On auth failure, bounce to the Flask login page.
export async function getJSON(path, opts = {}) {
  const r = await fetch(path, { credentials: 'same-origin', ...opts })
  if (r.status === 401 || (r.redirected && r.url.includes('/login'))) {
    window.location.href = '/login'
    throw new Error('unauthenticated')
  }
  if (!r.ok) throw new Error(`${path} → ${r.status}`)
  return r.json()
}

export function postJSON(path, body) {
  return sendJSON('POST', path, body)
}
export function patchJSON(path, body) {
  return sendJSON('PATCH', path, body)
}
export function delJSON(path) {
  return sendJSON('DELETE', path)
}
function sendJSON(method, path, body) {
  return getJSON(path, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
}

// Poll an endpoint on an interval. Returns { data, error, loading, refresh }.
export function usePoll(path, intervalMs = 5000) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(true)
  const timer = useRef(null)

  async function load() {
    try {
      const d = await getJSON(path)
      setData(d)
      setError(null)
    } catch (e) {
      setError(e)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    let alive = true
    load()
    timer.current = setInterval(() => alive && load(), intervalMs)
    return () => { alive = false; clearInterval(timer.current) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, intervalMs])

  return { data, error, loading, refresh: load }
}
