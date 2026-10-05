import { useEffect, useMemo, useRef, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, notify, post, usePoll, withProgress, type Overview } from '../api'
import { armImpact, confirmImpact } from '../impact'
import { Icon, IconBadge } from '../icons'
import { Empty, Legend, PageHeader, Panel, Verdict, tooltipStyle } from '../ui'

type K = Record<string, number>
type Year = {
  station: string; year: number; wall_s: number; replan_every_h: number
  solver: { solves: number; failures: number; mean_s: number; max_s: number }
  diesel_first: K; aurora: K; comparison: K
  daily: { date: string[]; base_fuel_l: number[]; aurora_fuel_l: number[]; base_ren_kwh: number[]; aurora_ren_kwh: number[]; demand_kwh: number[] }
}

const SCENARIOS = [
  { key: 'blizzard', label: 'Blizzard incoming', tag: 'B', proves: 'Storm Mode and safety', icon: 'blizzard', color: 'var(--warning)', params: { lead_h: 16, hours: 30, peak_ms: 32 } },
  { key: 'generator_failure', label: 'Generator failure', tag: 'C', proves: 'Resilience and load tiers', icon: 'generator', color: 'var(--s-diesel)', params: { hours: 24 } },
  { key: 'resupply_delay', label: 'Ship delayed 30 days', tag: 'D', proves: 'Mission assurance', icon: 'ship', color: 'var(--s-battery)', params: { days: 30 } },
  { key: 'wind_surplus', label: 'Wind surplus', tag: 'E', proves: 'Power + heat co-optimisation', icon: 'breeze', color: 'var(--s-wind)', params: { hours: 24, speed_ms: 14 } },
  { key: 'sensor_loss', label: 'Sensor freezes', tag: '', proves: 'Data validation', icon: 'sensor', color: 'var(--s-boiler)', params: { metric: 'MET.wind_ms', mode: 'frozen', hours: 6 } },
  { key: 'fuel_leak', label: 'Fuel leak', tag: '', proves: 'Fuel accounting', icon: 'leak', color: 'var(--critical)', params: { litres: 3000, hours: 6 } },
  { key: 'optimizer_failure', label: 'Optimiser crash', tag: '', proves: 'Fallback in one cycle', icon: 'cpu', color: 'var(--critical)', params: { hours: 2 } },
]

const PRESETS = [
  { key: 'reset', label: 'Reset station', detail: '4 Oct 06:00, no events, normal speed', icon: 'reset' },
  { key: 'blizzard', label: 'Blizzard demo', detail: 'Storm arrives in about 20 s: watch Storm Mode prepare', icon: 'blizzard' },
  { key: 'ship_delay', label: 'Ship-delay demo', detail: 'Resupply 30 days late: Fuel Survival Score and actions', icon: 'ship' },
]

// label, key, format, which direction is better
const ROWS: [string, string, (v: number) => string, 'lower' | 'higher' | 'same'][] = [
  ['Diesel used', 'fuel_l', (v) => fmt.kl(v), 'lower'],
  ['CO₂', 'co2_t', (v) => `${v.toFixed(0)} t`, 'lower'],
  ['Renewable fraction (power + heat)', 'renewable_fraction', (v) => fmt.pct(v, 1), 'higher'],
  ['Renewables curtailed', 'curtailed_pct', (v) => `${v.toFixed(1)}%`, 'lower'],
  ['Critical load served', 'critical_served_pct', (v) => `${v.toFixed(2)}%`, 'higher'],
  ['Generator run-hours', 'gen_run_hours', (v) => Math.round(v).toLocaleString('en-IN'), 'lower'],
  ['Low-load hours (<40%)', 'gen_low_load_hours', (v) => Math.round(v).toLocaleString('en-IN'), 'lower'],
  ['Mean generator loading', 'gen_mean_loading_pct', (v) => `${v.toFixed(0)}%`, 'higher'],
  ['Generator starts (min. run 2 h)', 'gen_starts', (v) => Math.round(v).toLocaleString('en-IN'), 'same'],
  ['Heat dumped', 'heat_dumped_mwh', (v) => `${v.toFixed(0)} MWh`, 'lower'],
  ['Power-to-heat', 'p2h_mwh', (v) => `${v.toFixed(0)} MWh`, 'higher'],
]

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

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

  const cal = useMemo(() => {
    if (!y) return { cells: [] as { d: string; f: number; lvl: number; i: number }[], lead: 0, max: 0 }
    const f = y.daily.date.map((_, i) => (y.daily.base_fuel_l[i] > 0 ? (y.daily.base_fuel_l[i] - y.daily.aurora_fuel_l[i]) / y.daily.base_fuel_l[i] : 0))
    const sorted = [...f].sort((p, q) => p - q)
    const q = (p: number) => sorted[Math.floor(p * (sorted.length - 1))]
    const cuts = [q(0.2), q(0.4), q(0.6), q(0.8)]
    const cells = y.daily.date.map((d, i) => ({ d, f: f[i], i, lvl: f[i] <= 0 ? 0 : 1 + cuts.filter((c) => f[i] > c).length }))
    const lead = (new Date(y.daily.date[0]).getDay() + 6) % 7 // Monday-first weeks
    return { cells, lead, max: Math.max(...f) }
  }, [y])

  const [busy, setBusy] = useState<string | null>(null)
  const runPreset = async (name: string) => {
    setBusy(name)
    try {
      armImpact()
      const label = PRESETS.find((p) => p.key === name)?.label ?? name
      const r = await withProgress(`Setting up “${label}”: rebuilding the station and re-planning. This can take up to a minute on a busy computer.`,
        () => post<{ tab: string; description: string; event?: string; message?: string; before?: Overview | null }>('/api/sim/preset', { name }))
      setMsg(r.description)
      notify(r.description)
      confirmImpact(r.event ?? 'reset', label, r.message ?? r.description, r.before ?? null, r.tab)
      onInjected(r.tab)
    } catch { /* post() already showed the reason */ } finally {
      setBusy(null)
    }
  }

  const inject = async (s: typeof SCENARIOS[number]) => {
    setBusy(s.key)
    try {
      armImpact()
      const r = await withProgress(`Injecting “${s.label}” and re-planning…`, () => post<{ message: string; before?: Overview | null }>('/api/sim/inject', { type: s.key, params: s.params }))
      const where = s.key === 'resupply_delay' ? 'fuel' : s.key === 'blizzard' || s.key === 'wind_surplus' ? 'forecast' : 'overview'
      setMsg(r.message)
      notify(`${r.message}. The panel at the top shows what it changes.`)
      confirmImpact(s.key, s.label, r.message, r.before, where)
      onInjected(where)
    } catch { /* post() already showed the reason */ } finally {
      setBusy(null)
    }
  }

  // fixed full-year axis; days not yet replayed are blank
  const shown = cum.map((c, i) => (i <= day ? { ...c, gap: [c.aurora, c.base] } : { d: c.d, aurora: null, base: null, gap: null }))
  const now = cum[day]
  const saved = now ? now.base - now.aurora : 0
  const LV = ['var(--tile-2)', 'color-mix(in srgb, var(--accent) 22%, white)', 'color-mix(in srgb, var(--accent) 42%, white)',
    'color-mix(in srgb, var(--accent) 65%, white)', 'color-mix(in srgb, var(--accent) 85%, white)', 'var(--accent)']

  return (
    <>
      <PageHeader step="Step 5 of 5 · Try scenarios" title="Put AURORA to the test"
        question="Start a ready-made demo or inject an event into the running station. Then go back to “Station now” to watch AURORA react. Below: a whole year of AURORA against today's rules.">
        {y && <Verdict status="ok">Over a full simulated year AURORA burned <b className="num">{fmt.kl(y.comparison.fuel_saved_l)} less diesel</b> ({y.comparison.fuel_saved_pct.toFixed(1)}%) than today's rules, with life support served 100% of the time.</Verdict>}
      </PageHeader>

      <div className="grid gap-5 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
        <Panel title="Ready-made demos" sub="One click sets up the station and opens the right page." icon={<IconBadge name="play" color="var(--accent)" />}>
          <div className="grid gap-2.5">
            {PRESETS.map((p) => (
              <button key={p.key} className={`btn !justify-start text-left !h-auto py-3 ${p.key === 'reset' ? '' : 'btn-accent'}`}
                disabled={busy !== null} onClick={() => runPreset(p.key)}>
                <Icon name={p.icon} size={22} />
                <span className="grid">
                  <span>{busy === p.key ? 'Setting up…' : p.label}</span>
                  <span className="text-[0.8rem] font-medium" style={{ opacity: 0.8 }}>{p.detail}</span>
                </span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel title="Inject a single event" sub="Both AURORA and a copy of the station running today's rules see the same event, so you can compare.">
          <div className="grid gap-2.5 grid-cols-1 sm:grid-cols-2 2xl:grid-cols-3">
            {SCENARIOS.map((s) => (
              <button key={s.key} onClick={() => inject(s)} disabled={busy !== null} aria-busy={busy === s.key}
                className="scenario text-left flex gap-3 items-start p-3.5 rounded-[18px] transition-colors"
                style={{ minHeight: 76, border: '1px solid var(--line)', background: busy === s.key ? 'var(--accent-soft)' : 'var(--card)', color: 'var(--ink)', font: 'inherit' }}>
                <IconBadge name={s.icon} color={s.color} size={42} />
                <span className="grid">
                  <b>{s.tag && <span className="num mr-1.5" style={{ color: 'var(--muted)' }}>{s.tag}</span>}{busy === s.key ? 'Injecting…' : s.label}</b>
                  <span className="text-[0.8rem]" style={{ color: 'var(--ink-2)' }}>Proves: {s.proves}</span>
                </span>
              </button>
            ))}
          </div>
          {msg && <p className="mt-3 mb-0 flex gap-2 items-center" role="status"><Icon name="check" size={18} color="var(--good)" />{msg}</p>}
        </Panel>
      </div>

      {error && !y ? <Panel title="A · Year in 60 seconds"><Empty>Run <code>uv run aurora year</code> to create the year comparison.</Empty></Panel> : !y ? <div className="card"><Empty>Loading the year…</Empty></div> : (
        <>
          <Panel title={`A · The year in 60 seconds: ${y.year} weather`}
            sub={`Cumulative diesel burned. The glowing gap between the lines is fuel AURORA never had to burn. ${y.solver.solves.toLocaleString('en-IN')} plans solved (mean ${y.solver.mean_s.toFixed(2)} s, ${y.solver.failures} failures).`}
            right={<div className="flex gap-2.5">
              <button className="btn btn-primary" onClick={() => { if (day >= n - 1) setDay(0); setPlaying((p) => !p) }}>
                <Icon name={playing ? 'pause' : 'play'} size={20} />{playing ? 'Pause' : day >= n - 1 ? 'Replay year' : 'Resume'}</button>
              <button className="btn" disabled={day >= n - 1 && !playing} onClick={() => { setPlaying(false); setDay(n - 1) }}>Skip to end</button>
            </div>}>
            <div className="grid gap-3 grid-cols-2 lg:grid-cols-4 mb-4">
              <div className="tile p-3.5"><div className="label">Date</div><div className="big text-[1.5rem] mt-1">{now ? new Date(now.d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' }) : '–'}</div></div>
              <div className="tile p-3.5"><div className="label">Diesel-first</div><div className="big text-[1.5rem] mt-1" style={{ color: 'var(--muted)' }}>{fmt.kl(now?.base ?? 0)}</div></div>
              <div className="tile p-3.5"><div className="label">AURORA</div><div className="big text-[1.5rem] mt-1">{fmt.kl(now?.aurora ?? 0)}</div></div>
              <div className="p-3.5 rounded-2xl" style={{ background: 'var(--accent-soft)' }}>
                <div className="label" style={{ color: 'var(--accent)' }}>Saved so far</div>
                <div className="big text-[1.5rem] mt-1" style={{ color: 'var(--accent)' }}>{fmt.kl(saved)}{now && now.base > 0 ? ` · ${(100 * saved / now.base).toFixed(1)}%` : ''}</div>
              </div>
            </div>
            <Legend items={[{ label: 'Diesel-first, cumulative', color: 'var(--s-base)', kind: 'dash' }, { label: 'AURORA, cumulative', color: 'var(--accent)', kind: 'line' }, { label: 'Fuel saved', color: 'var(--accent)', kind: 'band' }]} />
            <ResponsiveContainer width="100%" height={300}>
              <ComposedChart data={shown} margin={{ top: 10, right: 10, left: 0, bottom: 0 }}>
                <defs><linearGradient id="lab-gap" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#14B8A6" stopOpacity={0.35} /><stop offset="1" stopColor="#14B8A6" stopOpacity={0.08} /></linearGradient></defs>
                <CartesianGrid vertical={false} strokeDasharray="2 6" />
                <XAxis dataKey="d" type="category" interval={0} ticks={cum.filter((_, i) => i % 61 === 0).map((c) => c.d)} tickLine={false} axisLine={false}
                  tickFormatter={(s) => new Date(s).toLocaleDateString('en-GB', { month: 'short' })} />
                <YAxis tickFormatter={(v) => `${(v / 1000).toFixed(0)} kL`} width={58} tickLine={false} axisLine={false} domain={[0, Math.ceil((cum[n - 1]?.base ?? 1) / 50000) * 50000]} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.date(String(l))}
                  formatter={(v, nm) => [Array.isArray(v) ? `${fmt.kl(Number(v[1]) - Number(v[0]))} saved` : fmt.kl(Number(v)), nm]} />
                <Area dataKey="gap" stroke="none" fill="url(#lab-gap)" name="Gap" isAnimationActive={false} />
                <Line dataKey="base" stroke="var(--s-base)" strokeWidth={2.5} strokeDasharray="8 6" dot={false} name="Diesel-first" isAnimationActive={false} />
                <Line dataKey="aurora" stroke="var(--accent)" strokeWidth={3.5} dot={false} name="AURORA" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>

          <div className="grid gap-5 grid-cols-2 lg:grid-cols-4">
            {[
              { icon: 'drop', color: 'var(--s-diesel)', v: fmt.kl(y.comparison.fuel_saved_l), l: `diesel saved in a year (${y.comparison.fuel_saved_pct.toFixed(1)}%)` },
              { icon: 'leaf', color: 'var(--good)', v: `${y.comparison.co2_avoided_t.toFixed(0)} t`, l: 'CO₂ never emitted' },
              { icon: 'calendar', color: 'var(--s-battery)', v: `${y.comparison.reserve_days_gained.toFixed(0)} days`, l: 'more fuel reserve when the ship arrives' },
              { icon: 'generator', color: 'var(--s-wind)', v: `−${(100 * (1 - y.aurora.gen_run_hours / Math.max(1, y.diesel_first.gen_run_hours))).toFixed(0)}%`, l: 'engine running hours, so longer overhaul intervals' },
            ].map((x) => (
              <Panel key={x.l}>
                <div className="flex gap-3.5 items-center">
                  <IconBadge name={x.icon} color={x.color} size={52} />
                  <div className="min-w-0"><div className="big text-[1.6rem]">{x.v}</div><div className="text-sm" style={{ color: 'var(--ink-2)' }}>{x.l}</div></div>
                </div>
              </Panel>
            ))}
          </div>

          <div className="grid gap-5 grid-cols-1 2xl:grid-cols-2">
            <Panel title="Every day of the year" sub="One square per day. Brighter means AURORA saved a bigger share of that day's diesel.">
              <div className="scroll-x pb-2">
                <div className="grid gap-[3px]" style={{ gridTemplateRows: 'auto repeat(7, auto)', gridAutoFlow: 'column', gridAutoColumns: 'minmax(11px, 1fr)', minWidth: 640 }}>
                  {Array.from({ length: cal.lead }, (_, i) => <div key={`p${i}`} style={{ gridRow: i + 2 }} />)}
                  {cal.cells.map((c) => {
                    const dt = new Date(c.d)
                    const first = dt.getDate() <= 7 && (dt.getDay() + 6) % 7 === 0
                    return [
                      first ? <div key={`m${c.i}`} className="label" style={{ gridRow: 1, gridColumn: `${Math.floor((c.i + cal.lead) / 7) + 1} / span 4`, fontSize: 10 }}>{MONTHS[dt.getMonth()]}</div> : null,
                      <div key={c.d} title={`${fmt.date(c.d)}: ${(c.f * 100).toFixed(0)}% less diesel`}
                        style={{ gridRow: ((c.i + cal.lead) % 7) + 2, gridColumn: Math.floor((c.i + cal.lead) / 7) + 1, aspectRatio: '1', borderRadius: 3.5,
                          background: LV[c.lvl], opacity: c.i <= day ? 1 : 0.18, transition: 'opacity .2s' }} />,
                    ]
                  })}
                </div>
              </div>
              <div className="flex flex-wrap gap-1.5 items-center text-xs mt-2" style={{ color: 'var(--muted)' }}>
                Less saved{LV.map((c, i) => <span key={i} style={{ width: 13, height: 13, borderRadius: 3.5, background: c }} />)}More saved
                <span className="ml-auto">Best day: {(cal.max * 100).toFixed(0)}% less diesel</span>
              </div>
            </Panel>

            <Panel title="What changed, measure by measure" sub="Grey dot: today's rules. Teal dot: AURORA. The number on the right is the change; green means better.">
              <div className="grid gap-3">
                {ROWS.map(([label, k, f, better]) => {
                  const b = y.diesel_first[k], a = y.aurora[k]
                  const m = Math.max(Math.abs(a), Math.abs(b), 1e-9)
                  const pa = (a / m) * 100, pb = (b / m) * 100
                  const good = better === 'same' ? null : better === 'lower' ? a <= b : a >= b
                  const change = b ? ((a - b) / Math.abs(b)) * 100 : 0
                  return (
                    <div key={k} className="grid items-center gap-3" style={{ gridTemplateColumns: 'minmax(150px, 220px) 1fr 74px' }}>
                      <div className="min-w-0">
                        <div className="text-sm font-bold truncate">{label}</div>
                        <div className="num text-xs" style={{ color: 'var(--muted)' }}>{f(b)} → <span style={{ color: 'var(--ink)' }}>{f(a)}</span></div>
                      </div>
                      <div className="relative" style={{ height: 22 }}>
                        <div className="absolute left-0 right-0" style={{ top: 10, height: 2, background: 'var(--line)' }} />
                        <div className="absolute" style={{ top: 9, height: 4, borderRadius: 2, left: `${Math.min(pa, pb)}%`, width: `${Math.abs(pa - pb)}%`,
                          background: good === false ? 'var(--warning)' : 'linear-gradient(90deg, var(--accent), var(--s-base))', opacity: 0.7 }} />
                        <div className="absolute" style={{ top: 3, width: 16, height: 16, marginLeft: -8, borderRadius: 8, left: `${pb}%`, background: 'var(--s-base)' }} title={`Diesel-first ${f(b)}`} />
                        <div className="absolute" style={{ top: 2, width: 18, height: 18, marginLeft: -9, borderRadius: 9, left: `${pa}%`, background: 'var(--accent)', boxShadow: '0 0 0 3px var(--accent-soft)' }} title={`AURORA ${f(a)}`} />
                      </div>
                      <span className="num text-sm text-right" style={{ color: good === null ? 'var(--warning)' : good ? 'var(--good)' : 'var(--warning)' }}>
                        {Math.abs(change) < 0.05 ? 'same' : `${change > 0 ? '+' : '−'}${Math.abs(change).toFixed(0)}%`}
                      </span>
                    </div>
                  )
                })}
              </div>
              <p className="text-xs mt-3 mb-0" style={{ color: 'var(--muted)' }}>More engine starts is the trade-off: every start runs at least 2 hours and is charged as fuel in the optimiser. Simulated.</p>
            </Panel>
          </div>
        </>
      )}
    </>
  )
}
