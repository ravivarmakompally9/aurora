import { Area, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, usePoll } from '../api'
import { Empty, Legend, Panel, SERIES, tooltipStyle } from '../ui'

type F = {
  ready: boolean; issued: string; times: string[]
  load_p10: number[]; load_p50: number[]; load_p90: number[]; heat_p10: number[]; heat_p50: number[]; heat_p90: number[]
  pv_p10: number[]; pv_p50: number[]; pv_p90: number[]; wind_p10: number[]; wind_p50: number[]; wind_p90: number[]
  storm_prob: number[]; wind10: number[]; temp: number[]
  history: { times: string[]; load: number[]; heat: number[]; pv: number[]; wind: number[]; soc: number[]; tank: number[]; gen_kw: number[] }
  plan?: { times: string[]; units: number[]; gen_kw: number[]; batt_kw: number[]; soc: number[]; tank: number[]
    p2h_kw: number[]; boiler_kw: number[]; water_kw: number[]; curtail_kw: number[]; heat_rec_kw: number[]; fuel_l_total: number; solve_s: number; status: string }
}

const tick = (s: string) => fmt.time(s)

/** Screen 2: 48 h forecasts with uncertainty, and the dispatch plan AURORA will follow. */
export default function Forecast({ step }: { step: number }) {
  const { data: f } = usePoll<F>('/api/forecast', 4000, step)
  if (!f || !f.ready) return <Empty>Waiting for the first forecast…</Empty>

  const hist = f.history.times.map((t, i) => ({ t, load: f.history.load[i], heat: f.history.heat[i], pv: f.history.pv[i], wind: f.history.wind[i] }))
  const fc = f.times.map((t, i) => ({
    t, loadBand: [f.load_p10[i], f.load_p90[i]], load50: f.load_p50[i], heatBand: [f.heat_p10[i], f.heat_p90[i]], heat50: f.heat_p50[i],
    pvBand: [f.pv_p10[i], f.pv_p90[i]], pv50: f.pv_p50[i], windBand: [f.wind_p10[i], f.wind_p90[i]], wind50: f.wind_p50[i],
    storm: 100 * f.storm_prob[i], wind10: f.wind10[i],
  }))
  const demand = [...hist.map((h) => ({ t: h.t, load: h.load, heat: h.heat })), ...fc]
  const ren = [...hist.map((h) => ({ t: h.t, pvAct: h.pv, windAct: h.wind })), ...fc]
  const now = f.times[0]
  const p = f.plan
  const plan = p ? p.times.map((t, i) => ({
    t, gen: p.gen_kw[i], units: p.units[i], dis: Math.max(0, -p.batt_kw[i]), ch: -Math.max(0, p.batt_kw[i]),
    soc: 100 * p.soc[i], tank: 100 * p.tank[i], p2h: p.p2h_kw[i], boiler: p.boiler_kw[i], water: p.water_kw[i],
  })) : []

  return (
    <div className="grid gap-4">
      <div className="grid gap-4 grid-cols-1 xl:grid-cols-2">
        <Panel title="Electricity and heat demand" sub={`P10–P90 band, issued ${fmt.time(f.issued)}. Left of the line: measured.`}
          right={<Legend items={[{ label: 'Electric load', color: SERIES.load, kind: 'line' }, { label: 'Heat demand', color: SERIES.heat, kind: 'line' }, { label: 'P10–P90', color: 'var(--ink-2)', kind: 'band' }]} />}>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={demand} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="t" tickFormatter={tick} minTickGap={60} />
              <YAxis unit=" kW" width={64} />
              <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={(v) => (Array.isArray(v) ? v.map((x) => Number(x).toFixed(0)).join('–') : Number(v).toFixed(1)) + ' kW'} />
              <Area dataKey="heatBand" stroke="none" fill={SERIES.heat} fillOpacity={0.15} name="Heat P10–P90" isAnimationActive={false} />
              <Area dataKey="loadBand" stroke="none" fill={SERIES.load} fillOpacity={0.12} name="Load P10–P90" isAnimationActive={false} />
              <Line dataKey="heat" stroke={SERIES.heat} strokeWidth={2} dot={false} name="Heat (measured)" isAnimationActive={false} />
              <Line dataKey="load" stroke={SERIES.load} strokeWidth={2} dot={false} name="Load (measured)" isAnimationActive={false} />
              <Line dataKey="heat50" stroke={SERIES.heat} strokeWidth={2} strokeDasharray="5 3" dot={false} name="Heat forecast" isAnimationActive={false} />
              <Line dataKey="load50" stroke={SERIES.load} strokeWidth={2} strokeDasharray="5 3" dot={false} name="Load forecast" isAnimationActive={false} />
              <ReferenceLine x={now} stroke="var(--ink-2)" />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Solar and wind" sub="Physics model of sun angle, snow albedo, icing and cut-out, corrected by ML"
          right={<Legend items={[{ label: 'Solar', color: SERIES.solar, kind: 'line' }, { label: 'Wind', color: SERIES.wind, kind: 'line' }]} />}>
          <ResponsiveContainer width="100%" height={260}>
            <ComposedChart data={ren} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
              <CartesianGrid vertical={false} />
              <XAxis dataKey="t" tickFormatter={tick} minTickGap={60} />
              <YAxis unit=" kW" width={64} />
              <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={(v) => (Array.isArray(v) ? v.map((x) => Number(x).toFixed(0)).join('–') : Number(v).toFixed(1)) + ' kW'} />
              <Area dataKey="windBand" stroke="none" fill={SERIES.wind} fillOpacity={0.18} name="Wind P10–P90" isAnimationActive={false} />
              <Area dataKey="pvBand" stroke="none" fill={SERIES.solar} fillOpacity={0.18} name="Solar P10–P90" isAnimationActive={false} />
              <Line dataKey="windAct" stroke={SERIES.wind} strokeWidth={2} dot={false} name="Wind (measured)" isAnimationActive={false} />
              <Line dataKey="pvAct" stroke={SERIES.solar} strokeWidth={2} dot={false} name="Solar (measured)" isAnimationActive={false} />
              <Line dataKey="wind50" stroke={SERIES.wind} strokeWidth={2} strokeDasharray="5 3" dot={false} name="Wind forecast" isAnimationActive={false} />
              <Line dataKey="pv50" stroke={SERIES.solar} strokeWidth={2} strokeDasharray="5 3" dot={false} name="Solar forecast" isAnimationActive={false} />
              <ReferenceLine x={now} stroke="var(--ink-2)" />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      <Panel title="Blizzard risk" sub="Probability that wind exceeds the Storm Mode threshold (20 m/s), from forecast spread">
        <ResponsiveContainer width="100%" height={150}>
          <ComposedChart data={fc} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
            <CartesianGrid vertical={false} />
            <XAxis dataKey="t" tickFormatter={tick} minTickGap={60} />
            <YAxis unit="%" domain={[0, 100]} width={52} ticks={[0, 50, 100]} />
            <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={(v) => `${Number(v).toFixed(0)}%`} />
            <ReferenceLine y={50} stroke="var(--warning)" strokeDasharray="4 3" />
            <Area dataKey="storm" stroke="var(--warning)" fill="var(--warning)" fillOpacity={0.15} strokeWidth={2} name="Blizzard probability" isAnimationActive={false} />
          </ComposedChart>
        </ResponsiveContainer>
      </Panel>

      {p ? (
        <div className="grid gap-4 grid-cols-1 xl:grid-cols-2">
          <Panel title="Dispatch plan, next 48 h" sub={`MILP solved in ${p.solve_s.toFixed(2)} s (${p.status}). 15-min steps for 6 h, then hourly.`}
            right={<Legend items={[{ label: 'Generators', color: SERIES.diesel }, { label: 'Battery discharge', color: SERIES.battery }, { label: 'Battery charge (below 0)', color: SERIES.battery, kind: 'band' }, { label: 'Water plant', color: SERIES.load, kind: 'line' }]} />}>
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={plan} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="t" tickFormatter={tick} minTickGap={60} />
                <YAxis unit=" kW" width={64} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={(v) => `${Math.abs(Number(v)).toFixed(0)} kW`} />
                <ReferenceLine y={0} stroke="var(--ink-2)" />
                <Area dataKey="gen" stackId="s" type="stepAfter" stroke={SERIES.diesel} fill={SERIES.diesel} fillOpacity={0.85} name="Generators" isAnimationActive={false} />
                <Area dataKey="dis" stackId="s" type="stepAfter" stroke={SERIES.battery} fill={SERIES.battery} fillOpacity={0.85} name="Battery discharge" isAnimationActive={false} />
                <Area dataKey="ch" type="stepAfter" stroke={SERIES.battery} fill={SERIES.battery} fillOpacity={0.3} name="Battery charge" isAnimationActive={false} />
                <Line dataKey="water" stroke={SERIES.load} strokeWidth={2} dot={false} name="Water plant" isAnimationActive={false} type="stepAfter" />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>
          <Panel title="Storage plan" sub="Battery and thermal tank state of charge AURORA is steering toward"
            right={<Legend items={[{ label: 'Battery', color: SERIES.battery, kind: 'line' }, { label: 'Thermal tank', color: SERIES.heat, kind: 'line' }, { label: 'Power to heat', color: SERIES.heat, kind: 'band' }]} />}>
            <ResponsiveContainer width="100%" height={260}>
              <ComposedChart data={plan} margin={{ top: 6, right: 8, left: -10, bottom: 0 }}>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="t" tickFormatter={tick} minTickGap={60} />
                <YAxis unit="%" domain={[0, 100]} width={52} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={(v, n) => String(n).includes('heat') ? `${Number(v).toFixed(0)} kW` : `${Number(v).toFixed(0)}%`} />
                <Area dataKey="p2h" stroke="none" fill={SERIES.heat} fillOpacity={0.2} name="Power to heat (kW)" isAnimationActive={false} />
                <Line dataKey="soc" stroke={SERIES.battery} strokeWidth={2} dot={false} name="Battery" isAnimationActive={false} />
                <Line dataKey="tank" stroke={SERIES.heat} strokeWidth={2} dot={false} name="Thermal tank" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>
        </div>
      ) : <Panel title="Dispatch plan"><Empty>No valid plan: station is in fallback mode.</Empty></Panel>}
    </div>
  )
}
