import { useEffect, useState } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, post, usePoll } from '../api'
import { Empty, Legend, Panel, Stat, StatusChip, tooltipStyle } from '../ui'

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

/** Screen 4: will the fuel last until the ship arrives? (FR-19..21, FR-03 inputs) */
export default function Fuel() {
  const { data, reload } = usePoll<FuelResp>('/api/fuel', 10000)
  const [delay, setDelay] = useState<number | ''>('')
  const [resupply, setResupply] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    if (data && resupply === '') { setResupply(data.settings.resupply); setDelay(data.settings.delay_days) }
  }, [data, resupply])
  if (!data || !data.result) return <Empty>Running 1,000 fuel scenarios…</Empty>
  const r = data.result
  const a = r.aurora, b = r.diesel_first
  const fan = a.fan.dates.map((d, i) => ({ d, band: [a.fan.p10[i], a.fan.p90[i]], p50: a.fan.p50[i], base: b.fan.p50[i] }))
  const apply = async () => {
    setBusy(true)
    try { await post('/api/fuel/settings', { resupply, delay_days: delay === '' ? 0 : delay }); reload() } finally { setBusy(false) }
  }
  return (
    <div className="grid gap-4">
      <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-4">
        <Panel>
          <Stat big label="Fuel Survival Score" value={fmt.pct(a.score)} sub={`Target ${fmt.pct(r.threshold)} · ${a.fan.dates.length ? '1,000 weather and delay scenarios' : ''}`} />
          <div className="mt-2"><StatusChip status={r.level} /></div>
        </Panel>
        <Panel><Stat label="Diesel-first score" value={fmt.pct(b.score)} sub="Same scenarios under today's rules" /></Panel>
        <Panel><Stat label="Expected at arrival" value={fmt.kl(a.expected_at_arrival_l)} sub={`P10 ${fmt.kl(a.p10_at_arrival_l)} · reserve ${fmt.kl(a.reserve_l)}`} /></Panel>
        <Panel><Stat label="Burn rate" value={`${Math.round(a.burn_l_per_day).toLocaleString('en-IN')} L/day`} sub={`Diesel-first ${Math.round(b.burn_l_per_day).toLocaleString('en-IN')} L/day`} /></Panel>
      </div>

      <div className="grid gap-4 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_380px]">
        <Panel title="Fuel to resupply" sub={`Planned arrival ${fmt.date(a.planned_arrival)}. Band: P10–P90 of 1,000 scenarios.`}
          right={<Legend items={[{ label: 'AURORA P50', color: 'var(--ink)', kind: 'line' }, { label: 'P10–P90', color: 'var(--ink-2)', kind: 'band' }, { label: 'Diesel-first P50', color: 'var(--s-base)', kind: 'line' }, { label: 'Safety reserve', color: 'var(--critical)', kind: 'dash' }]} />}>
          <ResponsiveContainer width="100%" height={300}>
            <ComposedChart data={fan} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="d" tickFormatter={(s) => new Date(s).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })} minTickGap={40} />
              <YAxis tickFormatter={(v) => `${(v / 1000).toFixed(0)} kL`} width={56} />
              <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.date(String(l))}
                formatter={(v) => Array.isArray(v) ? v.map((x) => fmt.kl(Number(x))).join(' – ') : fmt.kl(Number(v))} />
              <Area dataKey="band" stroke="none" fill="var(--ink)" fillOpacity={0.12} name="AURORA P10–P90" isAnimationActive={false} />
              <Line dataKey="base" stroke="var(--s-base)" strokeWidth={2} dot={false} name="Diesel-first P50" isAnimationActive={false} />
              <Line dataKey="p50" stroke="var(--ink)" strokeWidth={2} dot={false} name="AURORA P50" isAnimationActive={false} />
              <ReferenceLine y={a.reserve_l} stroke="var(--critical)" strokeDasharray="5 4" />
              <ReferenceLine x={a.planned_arrival} stroke="var(--ink-2)" label={{ value: 'ship', position: 'insideTopRight', fill: 'var(--ink-2)' }} />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <div className="grid gap-4 content-start">
          <Panel title="Resupply inputs" sub="Station logistics (FR-03). Re-scores instantly.">
            <div className="grid gap-3">
              <label className="grid gap-1"><span className="label">Ship arrival date</span>
                <input id="resupply" type="date" value={resupply} onChange={(e) => setResupply(e.target.value)} /></label>
              <label className="grid gap-1"><span className="label">Known delay (days)</span>
                <input id="delay" type="number" min={0} max={120} value={delay} onChange={(e) => setDelay(e.target.value === '' ? '' : Number(e.target.value))} /></label>
              <button className="btn btn-primary" disabled={busy} onClick={apply}>{busy ? 'Scoring…' : 'Re-score fuel'}</button>
            </div>
          </Panel>
          <Panel title="Next fuel order" sub="One year of AURORA burn at P90, plus the reserve, minus fuel left at arrival">
            <Stat label="Recommended" value={fmt.kl(r.recommended_order_l)} sub={`Range ${fmt.kl(r.order_range_l[0])} – ${fmt.kl(r.order_range_l[1])}`} />
          </Panel>
        </div>
      </div>

      <Panel title="Conservation actions, ranked" sub="Each action re-scored on the same 1,000 scenarios. Litres are fuel kept at arrival.">
        {r.level !== 'ok' && (() => {
          const all = r.actions.find((x) => x.key === 'all')
          const enough = all && all.score_after >= r.threshold
          return (
            <div className="rounded-lg p-3 mb-3 flex flex-wrap items-center gap-3" role="alert"
              style={{ background: 'var(--surface-2)', borderLeft: `4px solid ${enough ? 'var(--warning)' : 'var(--critical)'}` }}>
              <StatusChip status={enough ? 'warning' : 'critical'} label={enough ? 'Act now' : 'Escalate to HQ'} />
              <span>{enough
                ? `Applying all actions restores the score to ${fmt.pct(all!.score_after)}.`
                : `Even all actions together reach only ${fmt.pct(all?.score_after ?? 0)}. Conservation alone is not enough: request priority resupply from NCPOR Goa.`}</span>
            </div>
          )
        })()}
        <div className="overflow-x-auto">
          <table className="w-full text-left" style={{ minWidth: 560 }}>
            <thead><tr className="label"><th className="py-2 pr-4">Action</th><th className="py-2 pr-4">What it means</th><th className="py-2 pr-4 text-right">Litres saved</th><th className="py-2 text-right">Score after</th></tr></thead>
            <tbody>
              {r.actions.map((x) => (
                <tr key={x.key} style={{ borderTop: '1px solid var(--line)' }}>
                  <td className="py-3 pr-4 font-medium">{x.title}</td>
                  <td className="py-3 pr-4 text-sm" style={{ color: 'var(--ink-2)' }}>{x.detail}</td>
                  <td className="py-3 pr-4 num text-right">{Math.round(x.litres_saved).toLocaleString('en-IN')}</td>
                  <td className="py-3 num text-right">{fmt.pct(x.score_after, 1)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
