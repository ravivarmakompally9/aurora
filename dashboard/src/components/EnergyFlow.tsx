import type { Overview } from '../api'
import { SERIES } from '../ui'

/** Live single-line diagram: sources -> station bus -> loads, plus the heat circuit below. */
export default function EnergyFlow({ d }: { d: Overview }) {
  const s = d.sources
  const w = (kw: number) => Math.max(1.5, Math.min(14, Math.sqrt(Math.abs(kw)) * 1.1))
  const live = (kw: number) => Math.abs(kw) > 0.5
  const batt = s.batt_kw  // + charging
  const busX = 450
  const srcs = [
    { key: 'pv', label: 'Solar PV', kw: s.pv_kw, color: SERIES.solar, note: `${s.pv_avail_kw.toFixed(0)} kW available`, y: 40 },
    { key: 'wind', label: 'Wind', kw: s.wind_kw, color: SERIES.wind, note: s.turbines_on ? `${s.wind_avail_kw.toFixed(0)} kW available` : 'Parked for storm', y: 110 },
    { key: 'gen', label: 'Generators', kw: s.gen_kw, color: SERIES.diesel, note: d.gens.map((g) => `${g.id} ${g.on ? g.loading_pct + '%' : g.available ? 'off' : 'TRIP'}`).join('  '), y: 180 },
    { key: 'bat', label: batt >= 0 ? 'Battery (charging)' : 'Battery', kw: -batt, color: SERIES.battery, note: `${(100 * d.storage.soc).toFixed(0)}% charged`, y: 250 },
  ]
  const t = d.loads.tiers
  const loads = [
    { label: 'Tier 1 · Life support', kw: t['1'] + d.loads.water_kw, note: d.loads.water_kw > 1 ? `incl. water plant ${d.loads.water_kw.toFixed(0)} kW` : 'ventilation, galley, medical', y: 40 },
    { label: 'Tier 2 · Comms & safety', kw: t['2'], note: 'satcom, control, emergency light', y: 100 },
    { label: 'Tier 3 · Science', kw: t['3'], note: 'instruments and labs', y: 160 },
    { label: 'Tier 4 · Comfort', kw: t['4'] + d.loads.laundry_kw, note: 'laundry, recreation', y: 220 },
    { label: 'Power to heat', kw: d.loads.p2h_kw, note: 'surplus into the thermal tank', y: 280, color: SERIES.heat },
  ]
  const h = d.heat
  const heatY = 360
  return (
    <svg viewBox="0 0 900 420" className="w-full h-auto" role="img" aria-label="Live energy flow">
      <style>{`.flow{stroke-dasharray:6 8;animation:flow 1.2s linear infinite}@keyframes flow{to{stroke-dashoffset:-14}}
        @media (prefers-reduced-motion: reduce){.flow{animation:none}}`}</style>
      {/* bus */}
      <rect x={busX - 6} y={20} width={12} height={290} rx={4} fill="var(--line)" />
      <text x={busX} y={14} textAnchor="middle" className="label" style={{ fill: 'var(--muted)', fontSize: 11 }}>STATION BUS</text>
      {srcs.map((x) => (
        <g key={x.key}>
          <rect x={20} y={x.y - 22} width={250} height={50} rx={8} fill="var(--surface-2)" stroke="var(--line)" />
          <rect x={20} y={x.y - 22} width={5} height={50} rx={2} fill={x.color} />
          <text x={36} y={x.y - 3} style={{ fill: 'var(--ink)', fontFamily: 'var(--font-display)', fontSize: 17, fontWeight: 600 }}>{x.label}</text>
          <text x={36} y={x.y + 16} style={{ fill: 'var(--ink-2)', fontSize: 11.5, fontFamily: 'var(--font-mono)' }}>{x.note}</text>
          <text x={262} y={x.y - 3} textAnchor="end" style={{ fill: 'var(--ink)', fontFamily: 'var(--font-mono)', fontSize: 15, fontWeight: 500 }}>
            {Math.abs(x.kw).toFixed(0)} kW</text>
          <path d={`M270 ${x.y} H${busX - 6}`} stroke={live(x.kw) ? x.color : 'var(--line)'} strokeWidth={w(x.kw)}
            className={live(x.kw) ? 'flow' : ''} style={x.kw < 0 ? { animationDirection: 'reverse' } : undefined} fill="none" />
        </g>
      ))}
      {loads.map((x) => (
        <g key={x.label}>
          <path d={`M${busX + 6} ${x.y} H630`} stroke={live(x.kw) ? (x.color ?? SERIES.load) : 'var(--line)'} strokeWidth={w(x.kw)}
            className={live(x.kw) ? 'flow' : ''} fill="none" opacity={x.color ? 1 : 0.55} />
          <rect x={630} y={x.y - 22} width={250} height={46} rx={8} fill="var(--surface-2)" stroke="var(--line)" />
          <text x={644} y={x.y - 4} style={{ fill: 'var(--ink)', fontFamily: 'var(--font-display)', fontSize: 16, fontWeight: 600 }}>{x.label}</text>
          <text x={644} y={x.y + 14} style={{ fill: 'var(--ink-2)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>{x.note}</text>
          <text x={870} y={x.y - 4} textAnchor="end" style={{ fill: 'var(--ink)', fontFamily: 'var(--font-mono)', fontSize: 14 }}>{x.kw.toFixed(0)} kW</text>
        </g>
      ))}
      {/* heat circuit */}
      <line x1={20} y1={318} x2={880} y2={318} stroke="var(--line)" strokeDasharray="2 4" />
      <text x={20} y={340} className="label" style={{ fill: 'var(--muted)', fontSize: 11 }}>HEAT CIRCUIT</text>
      {[
        { label: 'Waste heat', kw: h.recovered_kw - h.dump_kw, x: 20, color: SERIES.diesel },
        { label: 'Power to heat', kw: h.p2h_kw, x: 190, color: SERIES.heat },
        { label: `Tank ${(100 * d.storage.tank_soc).toFixed(0)}%`, kw: h.tank_dis_kw - h.tank_ch_kw, x: 360, color: SERIES.heat },
        { label: 'Oil boiler', kw: h.boiler_kw, x: 530, color: SERIES.boiler },
        { label: 'Heat demand', kw: h.demand_kw, x: 700, color: SERIES.load },
      ].map((x) => (
        <g key={x.label}>
          <rect x={x.x} y={heatY - 10} width={160} height={52} rx={8} fill="var(--surface-2)" stroke="var(--line)" />
          <rect x={x.x} y={heatY - 10} width={160} height={4} rx={2} fill={x.color} opacity={live(x.kw) ? 1 : 0.25} />
          <text x={x.x + 12} y={heatY + 12} style={{ fill: 'var(--ink)', fontFamily: 'var(--font-display)', fontSize: 15, fontWeight: 600 }}>{x.label}</text>
          <text x={x.x + 12} y={heatY + 32} style={{ fill: 'var(--ink-2)', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
            {x.label.startsWith('Tank') ? (x.kw > 0.5 ? `${x.kw.toFixed(0)} kW out` : x.kw < -0.5 ? `${(-x.kw).toFixed(0)} kW in` : 'holding') : `${Math.max(0, x.kw).toFixed(0)} kW`}
          </text>
        </g>
      ))}
    </svg>
  )
}
