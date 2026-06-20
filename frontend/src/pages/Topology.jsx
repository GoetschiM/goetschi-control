import { useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import { usePoll } from '../api.js'

// Renders the infra as tiers: Internet → UniFi → Proxmox → Hosts,
// with animated "flow" connectors between tiers.
export default function Topology() {
  const { data, loading } = usePoll('/api/live', 5000)
  const navigate = useNavigate()

  const topo = data?.topology || {}
  const hosts = data?.hosts || []

  const spine = useMemo(() => {
    const find = (k) => topo[k]
    return ['_internet', 'unifi', 'proxmox'].map(find).filter(Boolean)
  }, [topo])

  const leafHosts = useMemo(
    () => hosts.filter(h => h.key !== 'unifi' && h.key !== 'proxmox'),
    [hosts],
  )

  if (loading && !data) return <div className="center-msg">lädt …</div>

  return (
    <div className="topo">
      {spine.map((n, i) => (
        <div key={n.key || i} className="topo-tier">
          <TopoNode node={n} big />
          <Flow />
        </div>
      ))}
      <div className="group-title" style={{ marginTop: 4 }}>Hosts · {leafHosts.length}</div>
      <div className="topo-hosts">
        {leafHosts.map(h => (
          <button key={h.key} className={`topo-host s-border-${h.status}`}
            onClick={() => navigate(`/host/${encodeURIComponent(h.key)}`)}>
            <span className={`dot-s s-${h.status}`} />
            <span className="nm">{h.icon ? h.icon + ' ' : ''}{h.name}</span>
            <span className="ipx">{h.ip}</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function TopoNode({ node, big }) {
  const status = node.status || 'online'
  return (
    <div className={`topo-node ${big ? 'big' : ''} s-border-${status}`}>
      <span className={`dot-s s-${status}`} />
      <span>{node.label || node.key}</span>
      {node.ip && <span className="ipx">{node.ip}</span>}
    </div>
  )
}

function Flow() {
  return (
    <svg className="flow-conn" width="2" height="34" viewBox="0 0 2 34" preserveAspectRatio="none">
      <line x1="1" y1="0" x2="1" y2="34" className="flow-line" />
    </svg>
  )
}
