// Small shared presentational components.

export function Pill({ status }) {
  const s = status || 'offline'
  return <span className={`pill ${s}`}>{s}</span>
}

export function StatusDot({ status }) {
  return <span className={`dot-s s-${status || 'offline'}`} />
}

function level(pct) {
  if (pct == null) return ''
  if (pct >= 90) return 'crit'
  if (pct >= 75) return 'warn'
  return ''
}

export function MetricBar({ label, value, unit = '%', source }) {
  const pct = value == null ? null : Math.max(0, Math.min(100, value))
  return (
    <div className="metric">
      <div className="lbl">
        <span>{label}{source && <span className="src-tag"> · {source}</span>}</span>
        <b>{value == null ? '—' : `${value}${unit}`}</b>
      </div>
      <div className={`bar ${level(pct)}`}>
        <span style={{ width: `${pct ?? 0}%` }} />
      </div>
    </div>
  )
}

// Dependency-free inline SVG sparkline.
export function Sparkline({ points = [], width = 240, height = 44, color = 'var(--accent)' }) {
  const vals = points.map(p => (typeof p === 'number' ? p : p.v)).filter(v => v != null)
  if (vals.length < 2) return <div className="muted" style={{ fontSize: 12 }}>keine Daten</div>
  const min = Math.min(...vals), max = Math.max(...vals)
  const span = max - min || 1
  const step = width / (vals.length - 1)
  const d = vals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${(i * step).toFixed(1)} ${(height - ((v - min) / span) * (height - 6) - 3).toFixed(1)}`).join(' ')
  return (
    <svg className="spark" width="100%" viewBox={`0 0 ${width} ${height}`} preserveAspectRatio="none">
      <path d={d} fill="none" stroke={color} strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  )
}
