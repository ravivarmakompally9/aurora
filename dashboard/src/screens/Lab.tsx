import { useEffect, useMemo, useRef, useState } from 'react'
import { CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, post, usePoll } from '../api'
import { Empty, Legend, Panel, Stat, tooltipStyle } from '../ui'

type K = Record<string, number>
type Year = {
  station: string; year: number; wall_s: number; replan_every_h: number
  solver: { solves: number; failures: number; mean_s: number; max_s: number }
  diesel_first: K; aurora: K; comparison: K
  daily: { date: string[]; base_fuel_l: number[]; aurora_fuel_l: number[]; base_ren_kwh: number[]; aurora_ren_kwh: number[]; demand_kwh: number[] }
}

const SCENARIOS = [
  { key: 'blizzard', label: 'B · Blizzard incoming', proves: 'Storm Mode and safety', params: { lead_h: 16, hours: 30, peak_ms: 32 } },
  { key: 'generator_failure', label: 'C · Generator failure', proves: 'Resilience and load tiers', params: { hours: 24 } },
  { key: 'resupply_delay', label: 'D · Ship delayed 30 days', proves: 'Mission assurance', params: { days: 30 } },
  { key: 'wind_surplus', label: 'E · Wind surplus', proves: 'Power + heat co-optimisation', params: { hours: 24, speed_ms: 14 } },
  { key: 'sensor_loss', label: 'Sensor freezes', proves: 'Data validation', params: { metric: 'MET.wind_ms', mode: 'frozen', hours: 6 } },
  { key: 'fuel_leak', label: 'Fuel leak', proves: 'Fuel accounting', params: { litres: 3000, hours: 6 } },
  { key: 'optimizer_failure', label: 'Optimiser crash', proves: 'Fallback in one cycle', params: { hours: 2 } },
]

const ROWS: [string, string, (v: number) => string][] = [
  ['Diesel used', 'fuel_l', (v) => fmt.kl(v)],
  ['CO₂', 'co2_t', (v) => `${v.toFixed(0)} t`],
  ['Renewable fraction (power + heat)', 'renewable_fraction', (v) => fmt.pct(v, 1)],
  ['Renewables curtailed', 'curtailed_pct', (v) => `${v.toFixed(1)}%`],
  ['Critical load served', 'critical_served_pct', (v) => `${v.toFixed(2)}%`],
  ['Generator run-hours', 'gen_run_hours', (v) => Math.round(v).toLocaleString('en-IN')],
  ['Low-load hours (<40%)', 'gen_low_load_hours', (v) => Math.round(v).toLocaleString('en-IN')],
  ['Mean generator loading', 'gen_mean_loading_pct', (v) => `${v.toFixed(0)}%`],
  ['Generator starts (min. run 2 h)', 'gen_starts', (v) => Math.round(v).toLocaleString('en-IN')],
  ['Heat dumped', 'heat_dumped_mwh', (v) => `${v.toFixed(0)} MWh`],
  ['Power-to-heat', 'p2h_mwh', (v) => `${v.toFixed(0)} MWh`],
]

/** Screen 6: digital-twin lab. Scenario A replays the full year; B-E inject events into the live station. */
export default function Lab({ onInjected }: { onInjected: (tab: string) => void }) {
  const { data: y, error } = usePoll<Year>('/api/year', 60000)
  const [day, setDay] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const timer = useRef<number | undefined>(undefined)
  const n = y?.daily.date.length ?? 0
  const shownOnce = useRef(false)
  useEffect(() => { // open on the finished year; "Replay" animates it from 1 January
    if (n && !shownOnce.current) { shownOnce.current = true; setDay(n - 1) }
  }, [n])

  useEffect(() => { // clock-based: the replay always lasts 60 s, even if frames are slow or the tab is throttled
    if (!playing || !n) return
    const start = performance.now()
    const from = day
    timer.current = window.setInterval(() => {
      const d = Math.min(n - 1, from + Math.floor(((performance.now() - start) / 60000) * n))
      setDay(d)
      if (d >= n - 1) setPlaying(false)
    }, 100)
    return () => clearInterval(timer.current)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [playing, n])

  const cum = useMemo(() => {
    if (!y) return []
    let a = 0, b = 0
    return y.daily.date.map((d, i) => { a += y.daily.aurora_fuel_l[i]; b += y.daily.base_fuel_l[i]; return { d, aurora: a, base: b } })
  }, [y])

  const inject = async (s: typeof SCENARIOS[number]) => {
    const r = await post<{ message: string }>('/api/sim/inject', { type: s.key, params: s.params })
    setMsg(`${r.message}. Watch the ${s.key === 'resupply_delay' ? 'fuel screen' : 'overview'}.`)
    onInjected(s.key === 'resupply_delay' ? 'fuel' : s.key === 'blizzard' || s.key === 'wind_surplus' ? 'forecast' : 'overview')
  }

  // fixed full-year axis; days not yet replayed are blank
  const shown = cum.map((c, i) => (i <= day ? c : { d: c.d, aurora: null, base: null }))
  const now = cum[day]
  return (
    <div className="grid gap-4">
      <Panel title="Live scenarios" sub="Inject an event into the running station. AURORA and the diesel-first shadow both see it.">
        <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
          {SCENARIOS.map((s) => (
            <button key={s.key} className="btn text-left h-auto py-3" onClick={() => inject(s)}>
              <div>{s.label}</div>
              <div className="text-sm font-normal" style={{ fontFamily: 'var(--font-body)', color: 'var(--ink-2)' }}>Proves: {s.proves}</div>
            </button>
          ))}
        </div>
        {msg && <p className="mt-3" role="status">{msg}</p>}
      </Panel>

      {error && !y ? <Panel title="A · Year in 60 seconds"><Empty>Run <code>uv run aurora year</code> to create the year comparison.</Empty></Panel> : !y ? <Empty>Loading the year…</Empty> : (
        <>
          <Panel title={`A · Year in 60 seconds: ${y.year} weather at ${y.station[0].toUpperCase() + y.station.slice(1)}`}
            sub={`Full-year digital twin, 15-min physics, ${y.solver.solves.toLocaleString('en-IN')} MILP solves (mean ${y.solver.mean_s.toFixed(2)} s, ${y.solver.failures} failures). Simulated results, not a real-station claim.`}
            right={<div className="flex gap-2">
              <button className="btn btn-primary" onClick={() => { if (day >= n - 1) setDay(0); setPlaying((p) => !p) }}>{playing ? 'Pause' : day >= n - 1 ? 'Replay year' : 'Resume'}</button>
              <button className="btn" disabled={day >= n - 1 && !playing} onClick={() => { setPlaying(false); setDay(n - 1) }}>Skip to end</button>
            </div>}>
            <div className="grid gap-4 grid-cols-2 lg:grid-cols-4 mb-4">
              <Stat label="Date" value={now ? new Date(now.d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '–'} />
              <Stat label="Diesel-first" value={fmt.kl(now?.base ?? 0)} />
              <Stat label="AURORA" value={fmt.kl(now?.aurora ?? 0)} />
              <Stat label="Saved so far" value={fmt.kl((now?.base ?? 0) - (now?.aurora ?? 0))}
                sub={now && now.base > 0 ? `${(100 * (now.base - now.aurora) / now.base).toFixed(1)}% · ${(((now.base - now.aurora) * 2.68) / 1000).toFixed(0)} t CO₂` : undefined} />
            </div>
            <Legend items={[{ label: 'Diesel-first, cumulative', color: 'var(--s-base)', kind: 'line' }, { label: 'AURORA, cumulative', color: 'var(--ink)', kind: 'line' }]} />
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={shown} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="d" type="category" interval={0} ticks={cum.filter((_, i) => i % 61 === 0).map((c) => c.d)}
                  tickFormatter={(s) => new Date(s).toLocaleDateString('en-GB', { month: 'short' })} />
                <YAxis tickFormatter={(v) => `${(v / 1000).toFixed(0)} kL`} width={56} domain={[0, Math.ceil((cum[n - 1]?.base ?? 1) / 50000) * 50000]} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.date(String(l))} formatter={(v) => fmt.kl(Number(v))} />
                <Line dataKey="base" stroke="var(--s-base)" strokeWidth={2} dot={false} name="Diesel-first" isAnimationActive={false} />
                <Line dataKey="aurora" stroke="var(--ink)" strokeWidth={2} dot={false} name="AURORA" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>

          <Panel title="Full-year KPIs" sub="PRD §4 metrics from the side-by-side twin run">
            <div className="overflow-x-auto">
              <table className="w-full" style={{ minWidth: 520 }}>
                <thead><tr className="label text-left"><th className="py-2 pr-4">KPI</th><th className="py-2 pr-4 text-right">Diesel-first</th><th className="py-2 text-right">AURORA</th></tr></thead>
                <tbody>
                  {ROWS.map(([label, k, f]) => (
                    <tr key={k} style={{ borderTop: '1px solid var(--line)' }}>
                      <td className="py-2.5 pr-4">{label}</td>
                      <td className="py-2.5 pr-4 num text-right" style={{ color: 'var(--ink-2)' }}>{f(y.diesel_first[k])}</td>
                      <td className="py-2.5 num text-right font-medium">{f(y.aurora[k])}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="mt-3">
              Fuel saved <b className="num">{fmt.kl(y.comparison.fuel_saved_l)}</b> ({y.comparison.fuel_saved_pct.toFixed(1)}%),
              CO₂ avoided <b className="num">{y.comparison.co2_avoided_t.toFixed(0)} t</b>,
              reserve days gained <b className="num">{y.comparison.reserve_days_gained.toFixed(0)}</b>. <span className="label">Simulated</span>
            </p>
          </Panel>
        </>
      )}
    </div>
  )
}
