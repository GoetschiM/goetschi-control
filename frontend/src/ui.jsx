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

// Dependency-free time-series line chart (0–100% scale, grid + area fill).
export function MetricChart({ points = [], color = 'var(--accent)', label = '', unit = '%' }) {
  const W = 600, H = 180, padL = 30, padB = 16, padT = 8
  const vals = points.map(p => (typeof p === 'number' ? p : p.v)).filter(v => v != null)
  const last = vals.length ? vals[vals.length - 1] : null
  if (vals.length < 2) {
    return <div className="chart-card"><div className="chart-head"><span>{label}</span></div><div className="muted" style={{ padding: 24 }}>zu wenig Daten</div></div>
  }
  const max = 100, min = 0
  const innerW = W - padL, innerH = H - padB - padT
  const x = i => padL + (i / (vals.length - 1)) * innerW
  const y = v => padT + (1 - (v - min) / (max - min)) * innerH
  const line = vals.map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i).toFixed(1)} ${y(v).toFixed(1)}`).join(' ')
  const area = `${line} L ${x(vals.length - 1).toFixed(1)} ${y(0)} L ${x(0).toFixed(1)} ${y(0)} Z`
  const grid = [0, 25, 50, 75, 100]
  return (
    <div className="chart-card">
      <div className="chart-head">
        <span>{label}</span>
        <b style={{ color }}>{last != null ? `${last}${unit}` : '—'}</b>
      </div>
      <svg width="100%" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" className="chart-svg">
        {grid.map(g => (
          <g key={g}>
            <line x1={padL} x2={W} y1={y(g)} y2={y(g)} className="chart-grid" />
            <text x={padL - 6} y={y(g) + 3} className="chart-axis" textAnchor="end">{g}</text>
          </g>
        ))}
        <path d={area} fill={color} opacity="0.10" />
        <path d={line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" />
      </svg>
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
