import { useId } from 'react'
import { Icon } from '../icons'

export type Node = { key: string; label: string; kw: number; color: string; icon: string; note?: string }

const W = 960, LX = 220, BX = 470, RX = 720, NW = 10, GAP = 20, MIN = 3, SPAN = 230, TOP = 56

/** Power right now in three labelled stages: sources -> the station's power line -> uses. Band width is kW. */
export default function Sankey({ sources, sinks, busLabel }: { sources: Node[]; sinks: Node[]; busLabel: string }) {
  const id = useId().replace(/:/g, '')
  const tin = sources.reduce((a, s) => a + Math.max(0, s.kw), 0)
  const tout = sinks.reduce((a, s) => a + Math.max(0, s.kw), 0)
  const k = SPAN / Math.max(1, tin, tout)
  const place = (nodes: Node[]) => {
    let y = 0
    return nodes.map((n) => {
      const band = Math.max(0, n.kw) * k
      const h = Math.max(MIN, band)
      const out = { ...n, y, h, band }
      y += Math.max(h + GAP, n.note ? 52 : 42) // never let two label chips overlap
      return out
    })
  }
  const L = place(sources), R = place(sinks)
  const hL = L.length ? L[L.length - 1].y + L[L.length - 1].h : 0
  const hR = R.length ? R[R.length - 1].y + R[R.length - 1].h : 0
  const inner = Math.max(hL, hR, SPAN)
  const H = TOP + inner + 24
  const offL = TOP + (inner - hL) / 2, offR = TOP + (inner - hR) / 2
  const busH = Math.max(tin, tout) * k
  const busY = TOP + (inner - busH) / 2
  const ribbon = (x0: number, y0: number, x1: number, y1: number, h: number) => {
    const cx = (x0 + x1) / 2
    return `M${x0} ${y0} C${cx} ${y0} ${cx} ${y1} ${x1} ${y1} L${x1} ${y1 + h} C${cx} ${y1 + h} ${cx} ${y0 + h} ${x0} ${y0 + h}Z`
  }
  const live = (n: { band: number }) => n.band >= 0.3
  const startsIn = L.map((_, i) => busY + L.slice(0, i).reduce((a, x) => a + (live(x) ? x.band : 0), 0))
  const startsOut = R.map((_, i) => busY + R.slice(0, i).reduce((a, x) => a + (live(x) ? x.band : 0), 0))
  const kw = (v: number) => `${Math.abs(v).toFixed(0)} kW`
  const head = { font: '700 12px var(--font)', letterSpacing: '0.06em' }

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto" role="img"
      aria-label={`Power flow: ${sources.map((s) => `${s.label} ${kw(s.kw)}`).join(', ')}; uses: ${sinks.map((s) => `${s.label} ${kw(s.kw)}`).join(', ')}`}>
      <defs>
        {L.map((n) => (
          <linearGradient key={n.key} id={`${id}-${n.key}`} x1="0" x2="1">
            <stop offset="0" stopColor={n.color} stopOpacity={0.55} /><stop offset="1" stopColor={n.color} stopOpacity={0.18} />
          </linearGradient>
        ))}
        {R.map((n) => (
          <linearGradient key={n.key} id={`${id}-${n.key}`} x1="0" x2="1">
            <stop offset="0" stopColor={n.color} stopOpacity={0.14} /><stop offset="1" stopColor={n.color} stopOpacity={0.5} />
          </linearGradient>
        ))}
      </defs>
      <g fill="var(--muted)" style={head}>
        <text x={LX + NW} y="18" textAnchor="end">1. SOURCES</text>
        <text x={BX + 6} y="18" textAnchor="middle">2. POWER LINE</text>
        <text x={RX} y="18">3. USES</text>
      </g>
      <g fill="var(--ink)" style={{ font: '700 15px var(--font)' }}>
        <text x={LX + NW} y="38" textAnchor="end">{kw(tin)}</text>
        <text x={BX + 6} y="38" textAnchor="middle">{busLabel}</text>
        <text x={RX} y="38">{kw(tout)}</text>
      </g>
      {L.map((n, i) => live(n) && (
        <path key={n.key} d={ribbon(LX + NW, offL + n.y, BX, startsIn[i], n.band)} fill={`url(#${id}-${n.key})`}><title>{`${n.label}: ${kw(n.kw)}`}</title></path>
      ))}
      {R.map((n, i) => live(n) && (
        <path key={n.key} d={ribbon(BX + 12, startsOut[i], RX, offR + n.y, n.band)} fill={`url(#${id}-${n.key})`}><title>{`${n.label}: ${kw(n.kw)}`}</title></path>
      ))}
      <rect x={BX} y={busY} width="12" height={Math.max(4, busH)} rx="6" fill="var(--ink)" />

      {L.map((n) => {
        const cy = offL + n.y + n.h / 2
        return (
          <g key={n.key} opacity={n.kw > 0.3 ? 1 : 0.45}>
            <rect x={LX} y={offL + n.y} width={NW} height={n.h} rx={Math.min(5, n.h / 2)} fill={n.color} />
            <g transform={`translate(${LX - 212} ${cy - 17})`}>
              <rect width="200" height="34" rx="10" fill="#fff" stroke="var(--line-2)" />
              <g transform="translate(10 8)"><Icon name={n.icon} size={18} color={n.color} /></g>
              <text x="36" y="22" fill="var(--ink-2)" style={{ font: '600 12.5px var(--font)' }}>{n.label}</text>
              <text x="190" y="22" textAnchor="end" fill="var(--ink)" style={{ font: '700 13px var(--font)' }}>{kw(n.kw)}</text>
            </g>
          </g>
        )
      })}
      {R.map((n) => {
        const cy = offR + n.y + n.h / 2
        return (
          <g key={n.key} opacity={n.kw > 0.3 ? 1 : 0.45}>
            <rect x={RX} y={offR + n.y} width={NW} height={n.h} rx={Math.min(5, n.h / 2)} fill={n.color} />
            <g transform={`translate(${RX + 20} ${cy - (n.note ? 22 : 17)})`}>
              <rect width="214" height={n.note ? 44 : 34} rx="10" fill="#fff" stroke="var(--line-2)" />
              <g transform="translate(10 8)"><Icon name={n.icon} size={18} color={n.color} /></g>
              <text x="36" y="22" fill="var(--ink-2)" style={{ font: '600 12.5px var(--font)' }}>{n.label}</text>
              <text x="204" y="22" textAnchor="end" fill="var(--ink)" style={{ font: '700 13px var(--font)' }}>{kw(n.kw)}</text>
              {n.note && <text x="36" y="37" fill="var(--muted)" style={{ font: '500 11px var(--font)' }}>{n.note}</text>}
            </g>
          </g>
        )
      })}
    </svg>
  )
}

/** Two aligned stacked bars: where heat comes from and where it goes. */
export function BalanceBars({ rows }: { rows: { label: string; parts: { label: string; kw: number; color: string; ink: string }[] }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.parts.reduce((a, p) => a + Math.max(0, p.kw), 0)))
  return (
    <div className="grid gap-2" style={{ gridTemplateColumns: '76px 1fr', alignItems: 'center' }}>
      {rows.map((r) => {
        const sum = r.parts.reduce((a, p) => a + Math.max(0, p.kw), 0)
        return [
          <span key={`${r.label}-l`} className="text-[0.8125rem] font-semibold" style={{ color: 'var(--ink-2)' }}>{r.label}</span>,
          <div key={`${r.label}-b`} className="flex gap-[3px] overflow-hidden" style={{ height: 32, borderRadius: 10, width: `${Math.max(8, (sum / max) * 100)}%`, background: 'var(--tile-2)' }}>
            {r.parts.filter((p) => p.kw > 0.5).map((p) => (
              <div key={p.label} title={`${p.label}: ${p.kw.toFixed(0)} kW`} className="flex items-center px-3 overflow-hidden whitespace-nowrap text-[0.8125rem] font-semibold"
                style={{ flex: p.kw, background: p.color, color: p.ink, minWidth: 6, transition: 'flex .6s ease' }}>
                {p.kw / Math.max(sum, 1) > 0.2 ? `${p.label} · ${p.kw.toFixed(0)} kW` : ''}
              </div>
            ))}
            {sum < 0.5 && <span className="text-xs px-3 self-center" style={{ color: 'var(--muted)' }}>none</span>}
          </div>,
        ]
      })}
    </div>
  )
}
