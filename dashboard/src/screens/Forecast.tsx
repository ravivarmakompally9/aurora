import { useMemo } from 'react'
import { Area, CartesianGrid, ComposedChart, Line, ReferenceArea, ReferenceDot, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { fmt, usePoll } from '../api'
import { Icon } from '../icons'
import { Empty, Legend, PageHeader, Panel, SERIES, StatusChip, Verdict, tooltipStyle } from '../ui'

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
const kw = (v: unknown) => (Array.isArray(v) ? v.map((x) => Number(x).toFixed(0)).join('–') : Number(v).toFixed(1)) + ' kW'
const hhmm = (s: string) => new Date(s.replace(' ', 'T')).toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })
const NOW_LABEL = { value: 'NOW', position: 'insideTopLeft' as const, fill: 'var(--ink)', fontSize: 10, fontWeight: 700, fontFamily: 'var(--font)' }

function Gradients() {
  return (
    <defs>
      {Object.entries({ heat: SERIES.heat, load: 'var(--accent)', solar: SERIES.solar, wind: SERIES.wind, battery: SERIES.battery, diesel: SERIES.diesel }).map(([k, c]) => (
        <linearGradient key={k} id={`fc-${k}`} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor={c} stopOpacity={0.55} /><stop offset="1" stopColor={c} stopOpacity={0.03} />
        </linearGradient>
      ))}
    </defs>
  )
}

/** Screen 2: the next 48 h: weather, demand, renewables, and the dispatch plan AURORA will follow. */
export default function Forecast({ step, targets, stormActive, go }: { step: number; targets?: { soc: number; tank: number }; stormActive?: boolean; go: (t: string) => void }) {
  const { data: f } = usePoll<F>('/api/forecast', 4000, step)

  const view = useMemo(() => {
    if (!f || !f.ready) return null
    // history up to the forecast issue time only, so no time appears twice on the axis
    const hist = f.history.times.map((t, i) => ({ t, load: f.history.load[i], heat: f.history.heat[i], pvAct: f.history.pv[i], windAct: f.history.wind[i] }))
      .filter((h) => h.t < f.times[0])
    const fc = f.times.map((t, i) => ({
      t, loadBand: [f.load_p10[i], f.load_p90[i]], load50: f.load_p50[i], heatBand: [f.heat_p10[i], f.heat_p90[i]], heat50: f.heat_p50[i],
      pvBand: [f.pv_p10[i], f.pv_p90[i]], pv50: f.pv_p50[i], windBand: [f.wind_p10[i], f.wind_p90[i]], wind50: f.wind_p50[i],
    }))
    // 3-hourly glance cells
    const cells = []
    for (let i = 0; i + 1 < f.times.length && cells.length < 16; i += 12) {
      const sl = (a: number[]) => a.slice(i, i + 12)
      const mean = (a: number[]) => a.reduce((x, y) => x + y, 0) / Math.max(1, a.length)
      const prob = Math.max(...sl(f.storm_prob)), wind = mean(sl(f.wind10)), pv = mean(sl(f.pv_p50))
      cells.push({ t: f.times[i], prob, wind, temp: mean(sl(f.temp)), icon: prob >= 0.5 ? 'blizzard' : pv > 2 ? 'sun' : wind > 12 ? 'breeze' : 'moon' })
    }
    const hot = f.storm_prob.map((p, i) => (p >= 0.5 ? i : -1)).filter((i) => i >= 0)
    const window = hot.length ? { a: hot[0], b: hot[hot.length - 1], p: Math.max(...f.storm_prob) } : null
    // demand peak (forecast part)
    let pk = 0
    f.load_p50.forEach((v, i) => { if (v > f.load_p50[pk]) pk = i })
    const p = f.plan
    const plan = p ? p.times.map((t, i) => {
      const pv = f.pv_p50[i] ?? 0, wind = f.wind_p50[i] ?? 0
      const used = Math.max(0, pv + wind - (p.curtail_kw[i] ?? 0))
      const share = pv + wind > 0 ? used / (pv + wind) : 0
      return {
        t, gen: p.gen_kw[i], solar: pv * share, wind: wind * share, dis: Math.max(0, -p.batt_kw[i]), ch: -Math.max(0, p.batt_kw[i]),
        units: p.units[i], soc: 100 * p.soc[i], tank: 100 * p.tank[i], p2h: p.p2h_kw[i], boiler: p.boiler_kw[i],
      }
    }) : []
    return { demand: [...hist.map((h) => ({ t: h.t, load: h.load, heat: h.heat })), ...fc], ren: [...hist, ...fc], cells, window, pk, plan }
  }, [f])

  if (!f || !f.ready || !view) return <div className="card"><Empty>Waiting for the first forecast…</Empty></div>
  const now = f.times[0]
  const p = f.plan
  const w = view.window
  const maxUnits = Math.max(3, ...view.plan.map((x) => x.units))

  return (
    <>
      <PageHeader step="Step 2 of 5 · Next 48 hours" title="What is coming, and how will AURORA handle it?"
        question={`Forecast issued ${fmt.time(f.issued)}. Read top to bottom: the weather, what the station will need, then AURORA's plan to power it.`}
        actions={<>
          {p ? <StatusChip status="ok" label={`Plan ready in ${p.solve_s.toFixed(2)} s`} /> : <StatusChip status="fallback" />}
          <button className="btn" onClick={() => go('decisions')}>Why these choices<Icon name="arrow" size={16} /></button>
        </>}>
        <Verdict status={w ? 'warning' : 'ok'}>
          {w ? `Blizzard likely from ${fmt.time(f.times[w.a])} to ${fmt.time(f.times[w.b])} (${Math.round(w.p * 100)}%). AURORA is storing energy now and will keep a generator ready.`
            : 'No blizzard expected in the next 48 hours. AURORA is using sun, wind and the battery to keep generators off as much as it safely can.'}
          {p ? ` Planned diesel: ${fmt.l(p.fuel_l_total)}.` : ''}
        </Verdict>
      </PageHeader>

      <Panel title="Weather, every 3 hours" sub="Temperature and wind for the next 48 hours. Amber cells: blizzard likely." icon={<Icon name="clock" size={20} color="var(--accent)" />}>
        <div className="flex gap-1.5 scroll-x pb-1">
          {view.cells.map((c, i) => {
            const storm = c.prob >= 0.5
            const color = storm ? 'var(--warning)' : c.icon === 'sun' ? 'var(--s-solar)' : c.icon === 'breeze' ? 'var(--s-wind)' : 'var(--ink-2)'
            return (
              <div key={c.t} className="flex-1 grid justify-items-center gap-1 py-2.5 px-1 rounded-2xl" style={{ minWidth: 62,
                background: i === 0 ? 'var(--accent-soft)' : storm ? 'var(--warning-soft)' : 'var(--tile)',
                boxShadow: i === 0 ? 'inset 0 0 0 1px color-mix(in srgb, var(--accent) 45%, transparent)' : storm ? 'inset 0 0 0 1px color-mix(in srgb, var(--warning) 35%, transparent)' : undefined }}>
                <span className="label" style={{ color: i === 0 ? 'var(--accent)' : storm ? 'var(--warning)' : undefined }}>
                  {i === 0 ? 'Now' : hhmm(c.t) === '00:00' ? new Date(c.t.replace(' ', 'T')).toLocaleDateString('en-GB', { weekday: 'short' }) : hhmm(c.t).slice(0, 2)}
                </span>
                <Icon name={c.icon} size={24} color={color} />
                <span className="num text-sm font-semibold">{c.temp.toFixed(0)}°</span>
                <span className="num text-[0.7rem]" style={{ color: storm ? 'var(--warning)' : 'var(--muted)' }}>{c.wind.toFixed(0)} m/s</span>
              </div>
            )
          })}
        </div>
        <div className="mt-3.5 grid gap-1.5">
          <div className="relative flex overflow-hidden" style={{ height: 30, borderRadius: 11 }} aria-label="Blizzard probability over 48 hours">
            {f.storm_prob.map((pr, i) => (
              <div key={i} className="flex-1" style={{ background: pr >= 0.5 ? `color-mix(in srgb, var(--critical) ${Math.round(pr * 70)}%, var(--warning))` : `color-mix(in srgb, var(--warning) ${Math.round(pr * 140)}%, color-mix(in srgb, var(--good) 30%, transparent))` }} />
            ))}
            {w && (
              <div className="absolute inset-y-0 flex items-center justify-center text-[0.8rem] font-bold whitespace-nowrap overflow-hidden"
                style={{ left: `${(w.a / f.storm_prob.length) * 100}%`, width: `${((w.b - w.a + 1) / f.storm_prob.length) * 100}%`, color: '#1A0E00' }}>
                <Icon name="blizzard" size={16} style={{ marginRight: 6 }} />Blizzard {fmt.time(f.times[w.a])} → {fmt.time(f.times[w.b])} · {Math.round(w.p * 100)}%
              </div>
            )}
          </div>
          <div className="flex justify-between text-xs" style={{ color: 'var(--muted)' }}>
            <span>Storm risk now</span><span>{w ? 'Storm Mode prepares 12–24 h ahead' : 'No blizzard expected in 48 h'}</span><span>+48 h</span>
          </div>
        </div>
      </Panel>

      <div className="grid gap-5 grid-cols-1 xl:grid-cols-2">
        <Panel title="What the station will need" sub="Solid line: measured. Dashed line: forecast. Shaded band: the likely range (80% of outcomes fall inside)."
          right={<Legend items={[{ label: 'Heat demand', color: SERIES.heat, icon: 'thermo' }, { label: 'Electricity', color: 'var(--accent)', icon: 'bolt' }]} />}>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={view.demand} margin={{ top: 18, right: 10, left: -8, bottom: 0 }}>
              <Gradients />
              <CartesianGrid vertical={false} strokeDasharray="2 6" />
              <XAxis dataKey="t" tickFormatter={tick} minTickGap={70} tickLine={false} axisLine={false} />
              <YAxis unit=" kW" width={64} tickLine={false} axisLine={false} />
              <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={kw} />
              <Area dataKey="heatBand" stroke="none" fill={SERIES.heat} fillOpacity={0.16} name="Heat range" isAnimationActive={false} />
              <Area dataKey="loadBand" stroke="none" fill="var(--accent)" fillOpacity={0.16} name="Electricity range" isAnimationActive={false} />
              <Area dataKey="heat" stroke={SERIES.heat} strokeWidth={2.5} fill="url(#fc-heat)" name="Heat (measured)" isAnimationActive={false} />
              <Area dataKey="load" stroke="var(--accent)" strokeWidth={2.5} fill="url(#fc-load)" name="Electricity (measured)" isAnimationActive={false} />
              <Line dataKey="heat50" stroke={SERIES.heat} strokeWidth={2.5} strokeDasharray="6 5" dot={false} name="Heat forecast" isAnimationActive={false} />
              <Line dataKey="load50" stroke="var(--accent)" strokeWidth={2.5} strokeDasharray="6 5" dot={false} name="Electricity forecast" isAnimationActive={false} />
              <ReferenceLine x={now} stroke="var(--ink)" strokeOpacity={0.55} strokeDasharray="2 3" label={NOW_LABEL} />
              <ReferenceDot x={f.times[view.pk]} y={f.load_p50[view.pk]} r={6} fill="var(--accent)" stroke="var(--bg)" strokeWidth={2}
                label={{ value: `Peak ${f.load_p50[view.pk].toFixed(0)} kW · ${fmt.time(f.times[view.pk])}`, position: 'top', fill: 'var(--ink)', fontSize: 11, fontWeight: 700 }} />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>

        <Panel title="Free energy from sun and wind" sub="Every kilowatt from here is diesel the station does not burn. Shaded band: likely range."
          right={<Legend items={[{ label: 'Solar', color: SERIES.solar, icon: 'solar' }, { label: 'Wind', color: SERIES.wind, icon: 'wind' }]} />}>
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={view.ren} margin={{ top: 18, right: 10, left: -8, bottom: 0 }}>
              <Gradients />
              <CartesianGrid vertical={false} strokeDasharray="2 6" />
              <XAxis dataKey="t" tickFormatter={tick} minTickGap={70} tickLine={false} axisLine={false} />
              <YAxis unit=" kW" width={64} tickLine={false} axisLine={false} />
              <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={kw} />
              {w && <ReferenceArea x1={f.times[w.a]} x2={f.times[w.b]} fill="var(--warning)" fillOpacity={0.08}
                label={{ value: 'Blizzard: turbines may park', position: 'insideTop', fill: 'var(--warning)', fontSize: 11, fontWeight: 700 }} />}
              <Area dataKey="windBand" stroke="none" fill={SERIES.wind} fillOpacity={0.14} name="Wind range" isAnimationActive={false} />
              <Area dataKey="pvBand" stroke="none" fill={SERIES.solar} fillOpacity={0.14} name="Solar range" isAnimationActive={false} />
              <Area dataKey="windAct" stroke={SERIES.wind} strokeWidth={2.5} fill="url(#fc-wind)" name="Wind (measured)" isAnimationActive={false} />
              <Area dataKey="pvAct" stroke={SERIES.solar} strokeWidth={2.5} fill="url(#fc-solar)" name="Solar (measured)" isAnimationActive={false} />
              <Area dataKey="wind50" stroke={SERIES.wind} strokeWidth={2.5} strokeDasharray="6 5" fill="url(#fc-wind)" fillOpacity={0.6} name="Wind forecast" isAnimationActive={false} />
              <Area dataKey="pv50" stroke={SERIES.solar} strokeWidth={2.5} strokeDasharray="6 5" fill="url(#fc-solar)" fillOpacity={0.6} name="Solar forecast" isAnimationActive={false} />
              <ReferenceLine x={now} stroke="var(--ink)" strokeOpacity={0.55} strokeDasharray="2 3" label={NOW_LABEL} />
            </ComposedChart>
          </ResponsiveContainer>
        </Panel>
      </div>

      {p ? (
        <>
          <Panel title="AURORA's plan: who powers the station" sub={`Each colour is a source; the stack is the total. Orange is diesel, so less orange means less fuel. ${fmt.l(p.fuel_l_total)} planned over 48 h.`}
            right={<Legend items={[{ label: 'Generators', color: SERIES.diesel, icon: 'generator' }, { label: 'Battery', color: SERIES.battery, icon: 'battery' },
              { label: 'Wind', color: SERIES.wind, icon: 'wind' }, { label: 'Solar', color: SERIES.solar, icon: 'solar' }]} />}>
            <ResponsiveContainer width="100%" height={280}>
              <ComposedChart data={view.plan} margin={{ top: 12, right: 10, left: -8, bottom: 0 }} syncId="plan">
                <CartesianGrid vertical={false} strokeDasharray="2 6" />
                <XAxis dataKey="t" tickFormatter={tick} minTickGap={70} tickLine={false} axisLine={false} />
                <YAxis unit=" kW" width={64} tickLine={false} axisLine={false} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))} formatter={(v, n) => [`${Math.abs(Number(v)).toFixed(0)} kW`, n]} />
                {w && <ReferenceArea x1={f.times[w.a]} x2={f.times[Math.min(w.b, view.plan.length - 1)]} fill="var(--warning)" fillOpacity={0.07}
                  label={{ value: 'Storm: a generator stays on, battery holds reserve', position: 'insideTop', fill: 'var(--warning)', fontSize: 11, fontWeight: 700 }} />}
                <ReferenceLine y={0} stroke="var(--line-2)" />
                <Area dataKey="solar" stackId="s" type="stepAfter" stroke="none" fill={SERIES.solar} fillOpacity={0.9} name="Solar" isAnimationActive={false} />
                <Area dataKey="wind" stackId="s" type="stepAfter" stroke="none" fill={SERIES.wind} fillOpacity={0.9} name="Wind" isAnimationActive={false} />
                <Area dataKey="dis" stackId="s" type="stepAfter" stroke="none" fill={SERIES.battery} fillOpacity={0.9} name="Battery supplying" isAnimationActive={false} />
                <Area dataKey="gen" stackId="s" type="stepAfter" stroke="none" fill={SERIES.diesel} fillOpacity={0.88} name="Generators" isAnimationActive={false} />
                <Area dataKey="ch" type="stepAfter" stroke={SERIES.battery} strokeWidth={1.5} fill={SERIES.battery} fillOpacity={0.25} name="Battery charging" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
            <div className="text-xs -mt-1 mb-3 pl-14" style={{ color: 'var(--muted)' }}>Below zero: surplus going into the battery.</div>
            <div className="grid gap-1.5" style={{ gridTemplateColumns: '58px 1fr' }}>
              {Array.from({ length: maxUnits }, (_, k) => {
                const n = view.plan.length
                const segs: { a: number; b: number }[] = []
                view.plan.forEach((x, i) => {
                  if (x.units >= k + 1) {
                    const last = segs[segs.length - 1]
                    if (last && last.b === i - 1) last.b = i; else segs.push({ a: i, b: i })
                  }
                })
                return [
                  <span key={`l${k}`} className="text-xs self-center" style={{ color: 'var(--ink-2)' }}>{['1st unit', '2nd unit', '3rd unit', '4th unit'][k] ?? `Unit ${k + 1}`}</span>,
                  <div key={`b${k}`} className="relative" style={{ height: 14, borderRadius: 7, background: 'var(--tile)' }}>
                    {segs.map((sg) => (
                      <div key={sg.a} className="absolute inset-y-0" title={`${fmt.time(view.plan[sg.a].t)} → ${fmt.time(view.plan[sg.b].t)}`}
                        style={{ left: `${(sg.a / n) * 100}%`, width: `${((sg.b - sg.a + 1) / n) * 100}%`, borderRadius: 7,
                          background: `linear-gradient(90deg, var(--s-diesel), color-mix(in srgb, var(--s-diesel) 70%, #FFB37A))`, opacity: 1 - k * 0.15 }} />
                    ))}
                  </div>,
                ]
              })}
            </div>
            <div className="text-xs mt-2" style={{ color: 'var(--muted)' }}>Generators online over the 48 h plan. Each run lasts at least 2 hours to protect the engines.</div>
          </Panel>

          <Panel title="Energy stores" sub={stormActive ? 'Dashed amber lines: Storm Mode targets, reached 3 h before the wind arrives' : 'Battery and heat tank levels AURORA is steering toward'}
            right={<Legend items={[{ label: 'Battery', color: SERIES.battery, kind: 'line' }, { label: 'Heat tank', color: SERIES.heat, kind: 'line' }, { label: 'Power to heat', color: SERIES.heat, kind: 'band' }]} />}>
            <ResponsiveContainer width="100%" height={240}>
              <ComposedChart data={view.plan} margin={{ top: 12, right: 10, left: -8, bottom: 0 }} syncId="plan">
                <defs><linearGradient id="st-b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor={SERIES.battery} stopOpacity={0.35} /><stop offset="1" stopColor={SERIES.battery} stopOpacity={0} /></linearGradient></defs>
                <CartesianGrid vertical={false} strokeDasharray="2 6" />
                <XAxis dataKey="t" tickFormatter={tick} minTickGap={70} tickLine={false} axisLine={false} />
                <YAxis yAxisId="pct" unit="%" domain={[0, 100]} width={52} tickLine={false} axisLine={false} />
                <YAxis yAxisId="kw" orientation="right" hide domain={[0, 'dataMax + 50']} />
                <Tooltip {...tooltipStyle} labelFormatter={(l) => fmt.time(String(l))}
                  formatter={(v, n) => [String(n).includes('heat') && !String(n).includes('tank') ? `${Number(v).toFixed(0)} kW` : `${Number(v).toFixed(0)}%`, n]} />
                {w && <ReferenceArea yAxisId="pct" x1={f.times[w.a]} x2={f.times[Math.min(w.b, view.plan.length - 1)]} fill="var(--warning)" fillOpacity={0.07} />}
                {stormActive && targets && <ReferenceLine yAxisId="pct" y={100 * targets.soc} stroke="var(--warning)" strokeDasharray="6 5"
                  label={{ value: `battery target ${Math.round(100 * targets.soc)}%`, position: 'insideTopRight', fill: 'var(--warning)', fontSize: 11 }} />}
                {stormActive && targets && <ReferenceLine yAxisId="pct" y={100 * targets.tank} stroke="var(--warning)" strokeDasharray="2 4"
                  label={{ value: `tank target ${Math.round(100 * targets.tank)}%`, position: 'insideBottomRight', fill: 'var(--warning)', fontSize: 11 }} />}
                <Area yAxisId="kw" dataKey="p2h" stroke="none" fill={SERIES.heat} fillOpacity={0.18} name="Power to heat" isAnimationActive={false} />
                <Area yAxisId="pct" dataKey="soc" stroke={SERIES.battery} strokeWidth={3} fill="url(#st-b)" name="Battery" isAnimationActive={false} />
                <Line yAxisId="pct" dataKey="tank" stroke={SERIES.heat} strokeWidth={3} dot={false} name="Heat tank" isAnimationActive={false} />
              </ComposedChart>
            </ResponsiveContainer>
          </Panel>
        </>
      ) : <Panel title="Dispatch plan"><Empty>No valid plan: the station is on diesel-first fallback rules.</Empty></Panel>}
    </>
  )
}
