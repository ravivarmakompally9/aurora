import { useEffect, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, notify, post, usePoll, withProgress } from '../api'
import { Icon, IconBadge } from '../icons'
import { Callout, Empty, FutureDots, Legend, PageHeader, Panel, StatusChip, Verdict, tooltipStyle } from '../ui'

type Surv = {
  score: number; fuel_now_l: number; reserve_l: number; planned_arrival: string; expected_at_arrival_l: number
  p10_at_arrival_l: number; burn_l_per_day: number; fan: { dates: string[]; p10: number[]; p50: number[]; p90: number[] }
}
type FuelResp = {
  settings: { on_hand_kl: number; resupply: string; delay_days: number }; busy: boolean
  result: null | { level: string; threshold: number; aurora: Surv; diesel_first: Surv
    actions: { key: string; title: string; detail: string; litres_saved: number; score_after: number }[]
    recommended_order_l: number; order_range_l: number[] }
}

const ACTION_ICON: Record<string, string> = { science: 'science', setpoint: 'thermo', comfort: 'comfort', vehicles: 'fuel', all: 'spark' }
const actionIcon = (k: string) => ACTION_ICON[k] ?? 'leaf'
const day = (s: string) => new Date(s).getTime() / 864e5

/** Screen 4: will the fuel last until the ship arrives? (FR-19..21, FR-03 inputs) */
export default function Fuel({ go, refreshKey }: { go: (t: string) => void; refreshKey?: string }) {
  const { data, reload } = usePoll<FuelResp>('/api/fuel', 10000, refreshKey) // refetch as soon as the live score or delay changes
  const [delay, setDelay] = useState<number | ''>('')
  const [resupply, setResupply] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (data && resupply === '') { setResupply(data.settings.resupply); setDelay(data.settings.delay_days) }
  }, [data, resupply])
  if (!data || !data.result) return <div className="card"><Empty>Running 1,000 fuel scenarios…</Empty></div>
  const r = data.result
  const a = r.aurora, b = r.diesel_first
  const fan = a.fan.dates.map((d, i) => ({ d, band: [a.fan.p10[i], a.fan.p90[i]], p50: a.fan.p50[i], base: b.fan.p50[i] }))
  const apply = async () => {
    setBusy(true)
    try { await withProgress('Re-scoring 1,000 fuel futures with the new ship date…', () => post('/api/fuel/settings', { resupply, delay_days: delay === '' ? 0 : delay })); notify('Fuel re-scored with the new ship date.'); reload() }
    catch { /* post() already showed the reason */ } finally { setBusy(false) }
  }
  const start = a.fan.dates[0]
  const daysToShip = Math.max(0, Math.round(day(a.planned_arrival) - day(start)))
  const lasts = (s: Surv) => Math.max(0, (s.fuel_now_l - s.reserve_l) / Math.max(1, s.burn_l_per_day))
  const daysA = lasts(a), daysB = lasts(b)
  const margin = Math.round(daysA - daysToShip)
  const span = Math.max(daysA, daysB, daysToShip) * 1.08
  const all = r.actions.find((x) => x.key === 'all')
  const enough = all && all.score_after >= r.threshold
  const yMax = Math.ceil(Math.max(...a.fan.p90, a.fuel_now_l) / 20000) * 20000

  return (
    <>
      <PageHeader step="Step 4 of 5 · Will fuel last?" title="Will the fuel last until the ship?"
        question="Diesel arrives once a year. AURORA simulates 1,000 possible futures of weather, demand and ship delay, and counts how often the fuel stays above the safety reserve."
        actions={<button className="btn" onClick={() => go('lab')}>Next: try scenarios<Icon name="arrow" size={16} /></button>}>
        <Verdict status={r.level}>
          {r.level === 'ok'
            ? `Safe. Fuel stays above the reserve in ${Math.round(a.score * 100)} of 100 futures, with about ${Math.max(0, margin)} days to spare when the ship arrives.`
            : r.level === 'critical'
              ? `Fuel is likely to run short: it lasts until the ship in only ${Math.round(a.score * 100)} of 100 futures (target ${Math.round(r.threshold * 100)}). See below what helps, and when to call HQ.`
              : `Fuel is tight: it lasts in ${Math.round(a.score * 100)} of 100 futures (target ${Math.round(r.threshold * 100)}). The actions at the bottom of this page show what helps most.`}
        </Verdict>
      </PageHeader>

      <div className="grid gap-5 grid-cols-1 lg:grid-cols-3">
        {[{ s: a, name: 'With AURORA', status: r.level, color: 'var(--good)' }, { s: b, name: "With today's rules", status: b.score >= r.threshold ? 'ok' : b.score >= 0.6 ? 'warning' : 'critical', color: 'var(--s-base)' }].map((x) => (
          <Panel key={x.name}>
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="label">{x.name}</div>
                <div className="big text-[2.4rem] mt-1">{Math.round(x.s.score * 100)}<span className="unit text-[1.2rem]">of 100 futures</span></div>
              </div>
              <StatusChip status={x.status} />
            </div>
            <div className="mt-3"><FutureDots share={x.s.score} color={x.color} size={10} gap={4} /></div>
            <div className="text-[0.8125rem] mt-3" style={{ color: 'var(--ink-2)' }}>
              Burns <b className="num">{Math.round(x.s.burn_l_per_day).toLocaleString('en-IN')} L a day</b> · expected <b className="num">{fmt.kl(x.s.expected_at_arrival_l)}</b> left at the ship
            </div>
          </Panel>
        ))}
        <Panel>
          <div className="label">Days of fuel vs days to the ship</div>
          <div className="big text-[2.4rem] mt-1" style={{ color: margin >= 0 ? 'var(--accent)' : 'var(--critical)' }}>{margin >= 0 ? '+' : ''}{margin}<span className="unit text-[1.2rem]">days {margin >= 0 ? 'to spare' : 'short'}</span></div>
          <div className="grid gap-2.5 mt-4">
            {[{ v: daysA, c: 'var(--accent)', l: 'AURORA', t: `${Math.round(daysA)} days` }, { v: daysB, c: 'var(--s-base)', l: "Today's rules", t: `${Math.round(daysB)} days` }].map((x) => (
              <div key={x.l}>
                <div className="flex justify-between text-[0.8125rem] mb-1"><span style={{ color: 'var(--ink-2)' }}>{x.l}</span><b className="num">{x.t}</b></div>
                <div className="relative" style={{ height: 12, borderRadius: 12, background: 'var(--tile-2)' }}>
                  <div style={{ width: `${(x.v / span) * 100}%`, height: '100%', borderRadius: 12, background: x.c }} />
                  <div className="absolute" title="Ship arrives" style={{ left: `${(daysToShip / span) * 100}%`, top: -5, bottom: -5, width: 2, background: 'var(--ink)' }} />
                </div>
              </div>
            ))}
          </div>
          <div className="text-xs mt-3 flex items-center gap-1.5" style={{ color: 'var(--muted)' }}><Icon name="ship" size={14} />Black line: ship on {fmt.date(a.planned_arrival)}, in {daysToShip} days.</div>
        </Panel>
      </div>

      <div className="grid gap-5 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Fuel level from today to the ship" sub="The line shows the expected fuel level each day; the shaded band covers 80% of the 1,000 futures. Falling into the red zone means eating into the safety reserve."
          right={<Legend items={[{ label: 'AURORA, expected', color: 'var(--accent)', kind: 'line' }, { label: 'Likely range', color: 'var(--accent)', kind: 'band' },
            { label: "Today's rules", color: 'var(--s-base)', kind: 'dash' }]} />}>
          <ResponsiveContainer width="100%" height={340}>
            <ComposedChart data={fan} margin={{ top: 30, right: 16, left: 4, bottom: 0 }}>
              <defs>
                <linearGradient id="fu-band" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#14B8A6" stopOpacity={0.28} /><stop offset="1" stopColor="#14B8A6" stopOpacity={0.08} /></linearGradient>
                <pattern id="fu-red" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="3" height="8" fill="rgba(248,113,113,.35)" /></pattern>
              </defs>
              <CartesianGrid vertical={false} strokeDasharray="2 6" />
              <XAxis dataKey="d" tickFormatter={(s) => new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} minTickGap={50} tickLine={false} axisLine={false} />
              <YAxis tickFormatter={(v) => `${(v / 1000).toFixed(0)} kL`} width={58} domain={[0, yMax]} tickLine={false} axisLine={false} />
              <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.date(String(l))}
                formatter={(v, n) => [Array.isArray(v) ? v.map((x) => fmt.kl(Number(x))).join(' – ') : fmt.kl(Number(v)), n]} />
              <ReferenceArea y1={0} y2={a.reserve_l} fill="url(#fu-red)" stroke="none"
                label={{ value: `Safety reserve ${fmt.kl(a.reserve_l)}`, position: 'insideBottomLeft', fill: 'var(--critical)', fontSize: 12, fontWeight: 700 }} />
              <ReferenceLine y={a.reserve_l} stroke="var(--critical)" strokeDasharray="6 5" strokeWidth={2} />
              <Area dataKey="band" stroke="none" fill="url(#fu-band)" name="AURORA range" isAnimationActive={false} />
              <Line dataKey="base" stroke="var(--s-base)" strokeWidth={2.5} strokeDasharray="7 6" dot={false} name="Today's rules" isAnimationActive={false} />
              <Line dataKey="p50" stroke="var(--accent)" strokeWidth={3.5} dot={false} name="AURORA expected" isAnimationActive={false} />
              <ReferenceLine x={a.planned_arrival} stroke="var(--ink)" strokeOpacity={0.7}
                label={(props: { viewBox?: { x: number; y: number } }) => {
                  const x = props.viewBox?.x ?? 0, y = props.viewBox?.y ?? 0
                  return (
                    <g transform={`translate(${x - 14} ${y - 30})`}>
                      <Icon name="ship" size={28} color="var(--s-diesel)" />
                      <text x="34" y="18" fill="var(--ink)" style={{ font: '700 12px var(--font)' }}>Ship</text>
                    </g>
                  )
                }} />
              <ReferenceDot x={a.planned_arrival} y={a.expected_at_arrival_l} r={6} fill="var(--accent)" stroke="var(--bg)" strokeWidth={2}
                label={{ value: `${fmt.kl(a.expected_at_arrival_l)} left`, position: 'bottom', offset: 12, fill: 'var(--accent)', fontSize: 12, fontWeight: 700 }} />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="flex flex-wrap gap-2.5 mt-2">
            <span className="pill" style={{ background: 'color-mix(in srgb, var(--accent) 12%, transparent)', color: 'var(--ink)' }}>AURORA at arrival: <b className="num">{fmt.kl(a.expected_at_arrival_l)}</b> (worst 10%: {fmt.kl(a.p10_at_arrival_l)})</span>
            <span className="pill" style={{ background: 'var(--tile)', color: 'var(--ink-2)' }}>Today's rules: <b className="num">{fmt.kl(b.expected_at_arrival_l)}</b></span>
            <span className="pill" style={{ background: 'var(--tile)', color: 'var(--ink-2)' }}>Burn {Math.round(a.burn_l_per_day).toLocaleString('en-IN')} vs {Math.round(b.burn_l_per_day).toLocaleString('en-IN')} L/day</span>
          </div>
        </Panel>

        <div className="grid gap-5 content-start">
          <Panel title="Resupply inputs" sub="Station logistics (FR-03). Re-scores the 1,000 futures." icon={<IconBadge name="calendar" color="var(--accent)" />}>
            <div className="grid gap-3">
              <label className="grid gap-1.5"><span className="label">Ship arrival date</span>
                <input id="resupply" type="date" value={resupply} onChange={(e) => setResupply(e.target.value)} /></label>
              <label className="grid gap-1.5"><span className="label">Known delay (days)</span>
                <input id="delay" type="number" min={0} max={120} value={delay} onChange={(e) => setDelay(e.target.value === '' ? '' : Number(e.target.value))} /></label>
              <button className="btn btn-primary" disabled={busy} onClick={apply}><Icon name="reset" size={18} />{busy ? 'Scoring…' : 'Re-score fuel'}</button>
            </div>
          </Panel>
          <Panel>
            <div className="flex gap-3.5 items-center">
              <IconBadge name="ship" color="var(--s-diesel)" size={56} />
              <div>
                <div className="label">Next fuel order</div>
                <div className="num text-[1.6rem] font-semibold">{fmt.kl(r.recommended_order_l)}</div>
                <div className="text-xs" style={{ color: 'var(--ink-2)' }}>Range {fmt.kl(r.order_range_l[0])} – {fmt.kl(r.order_range_l[1])}</div>
              </div>
            </div>
            <p className="text-xs mt-3 mb-0" style={{ color: 'var(--muted)' }}>One year of AURORA burn at P90, plus the reserve, minus the fuel expected at arrival.</p>
          </Panel>
        </div>
      </div>

      <Panel title="If fuel runs short: what helps most" sub="Grey: today's score. Teal: how much each action adds. Black tick: the target. Litres are fuel kept for the ship's arrival.">
        {r.level !== 'ok' && (
          <div className="mb-4" role="alert">
            <Callout status={enough ? 'warning' : 'critical'}>
              <div className="flex flex-wrap items-center gap-3">
                <StatusChip status={enough ? 'warning' : 'critical'} label={enough ? 'Act now' : 'Escalate to HQ'} />
                <span>{enough
                  ? `Applying all actions restores the score to ${fmt.pct(all!.score_after)}.`
                  : `Even all actions together reach only ${fmt.pct(all?.score_after ?? 0)}. Conservation alone is not enough: request priority resupply from NCPOR Goa.`}</span>
              </div>
            </Callout>
          </div>
        )}
        <div className="grid gap-3.5">
          {r.actions.map((x) => {
            const lift = Math.max(0, x.score_after - a.score)
            return (
              <div key={x.key} className="grid items-center gap-x-4 gap-y-2 grid-cols-[1fr_auto] md:grid-cols-[minmax(200px,300px)_minmax(160px,1fr)_120px] pb-3 md:pb-0 border-b md:border-0" style={{ borderColor: 'var(--line)' }}>
                <div className="flex gap-3 items-center min-w-0 col-span-2 md:col-span-1">
                  <IconBadge name={actionIcon(x.key)} color={x.key === 'all' ? 'var(--accent)' : 'var(--s-wind)'} size={38} />
                  <div className="min-w-0">
                    <div className="font-bold" style={{ color: x.key === 'all' ? 'var(--accent)' : undefined }}>{x.title}</div>
                    <div className="text-xs" style={{ color: 'var(--muted)' }}>{x.detail}</div>
                  </div>
                </div>
                <div className="relative" style={{ height: 22, borderRadius: 11, background: 'var(--tile)' }}>
                  <div className="absolute inset-y-0 left-0" style={{ width: `${a.score * 100}%`, borderRadius: 11, background: 'var(--s-base)', opacity: .45 }} />
                  <div className="absolute inset-y-0" style={{ left: `${a.score * 100}%`, width: `${lift * 100}%`, borderRadius: 11,
                    background: x.key === 'all' ? 'var(--accent-2)' : 'var(--accent)', transition: 'width .6s' }} />
                  <div className="absolute" style={{ left: `${r.threshold * 100}%`, top: -5, bottom: -5, width: 2, background: 'var(--ink)' }} title="Target" />
                </div>
                <div className="text-right">
                  <div className="num">{fmt.pct(a.score)} → <b>{fmt.pct(x.score_after, 0)}</b></div>
                  <div className="num text-xs" style={{ color: 'var(--muted)' }}>+{Math.round(x.litres_saved).toLocaleString('en-IN')} L</div>
                </div>
              </div>
            )
          })}
        </div>
      </Panel>
    </>
  )
}
