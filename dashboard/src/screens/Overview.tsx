import { useState } from 'react'
import type { Tour } from '../App'
import type { Overview as O } from '../api'
import { fmt, notify, post, withProgress } from '../api'
import Sankey, { BalanceBars } from '../components/Sankey'
import { Icon, IconBadge } from '../icons'
import { Bar, Callout, FutureDots, Kpi, PageHeader, Panel, SERIES, SplitBar, StatusChip, Verdict } from '../ui'

function GettingStarted({ tour, go }: { tour: Tour; go: (t: string) => void }) {
  const [busy, setBusy] = useState(false)
  const runDemo = async () => {
    setBusy(true)
    try { await withProgress('Setting up the blizzard demo: rebuilding the station and forecasting the storm. This can take up to a minute on a busy computer.', () => post('/api/sim/preset', { name: 'blizzard' })); notify('Blizzard demo started: a storm arrives in about 16 simulated hours.'); tour.mark('demo'); go('forecast') }
    catch { /* post() already showed the reason */ } finally { setBusy(false) }
  }
  const steps = [
    { k: 'overview', t: 'Read the station status', d: 'This page: is the station safe, how much fuel is left, where the power goes.', act: null },
    { k: 'demo', t: 'Throw a blizzard at the station', d: 'Starts a storm 16 h ahead. Watch AURORA fill the battery and heat tank before it hits.', act: { label: busy ? 'Starting…' : 'Start demo', fn: runDemo } },
    { k: 'forecast', t: "See AURORA's 48-hour plan", d: 'Weather, demand, and which generator runs when.', act: { label: 'Open', fn: () => go('forecast') } },
    { k: 'fuel', t: 'Check the fuel lasts until the ship', d: '1,000 simulated futures, and what to do if it is tight.', act: { label: 'Open', fn: () => go('fuel') } },
    { k: 'lab', t: 'Compare a full year', d: "AURORA against today's diesel-first rules on the same weather.", act: { label: 'Open', fn: () => go('lab') } },
  ]
  const n = steps.filter((s) => tour.done[s.k]).length
  const next = steps.find((s) => !tour.done[s.k])
  if (!next) {
    return (
      <div className="card px-5 py-3.5 flex flex-wrap items-center gap-3 rise">
        <span style={{ color: 'var(--accent)' }}><Icon name="done" size={20} /></span>
        <span className="font-semibold">You have seen all five steps.</span>
        <span className="text-sm" style={{ color: 'var(--ink-2)' }}>Try more events on “Try scenarios”, or replay the full year.</span>
        <button className="btn btn-ghost !min-h-[38px] !px-3 !text-sm ml-auto" onClick={() => tour.hide(true)}>Hide</button>
      </div>
    )
  }
  return (
    <Panel title="Getting started: see AURORA in five steps" sub="New here? Follow these in order. Each takes under a minute."
      icon={<IconBadge name="target" color="var(--accent)" />}
      right={<div className="flex items-center gap-3">
        <span className="text-sm" style={{ color: 'var(--ink-2)' }}><b className="num" style={{ color: 'var(--ink)' }}>{n} of {steps.length}</b> done</span>
        <button className="btn btn-ghost !min-h-[38px] !px-3 !text-sm" onClick={() => tour.hide(true)}>Hide</button>
      </div>}>
      <div className="flex gap-1.5 mb-4">{steps.map((s) => <div key={s.k} className="flex-1" style={{ height: 6, borderRadius: 6, background: tour.done[s.k] ? 'var(--accent)' : 'var(--tile-2)' }} />)}</div>
      <ol className="grid gap-2 m-0 p-0 list-none">
        {steps.map((s, i) => {
          const done = tour.done[s.k], isNext = next?.k === s.k
          return (
            <li key={s.k} className="flex items-center gap-3.5 rounded-xl px-3 py-2.5" style={{ background: isNext ? 'var(--accent-soft)' : 'transparent' }}>
              <span className="badge num text-sm font-bold" style={{ width: 30, height: 30, borderRadius: 30, background: done ? 'var(--accent)' : 'var(--card)',
                color: done ? '#fff' : 'var(--ink-2)', border: done ? 'none' : '1.5px solid var(--line-2)' }}>
                {done ? <Icon name="check" size={16} /> : i + 1}
              </span>
              <div className="flex-1 min-w-0">
                <div className="font-semibold" style={{ color: done ? 'var(--muted)' : 'var(--ink)', textDecoration: done ? 'line-through' : 'none' }}>{s.t}</div>
                <div className="text-[0.8125rem]" style={{ color: 'var(--muted)' }}>{s.d}</div>
              </div>
              {s.act && !done && (
                <button className={`btn ${isNext ? 'btn-accent' : ''} !min-h-[40px] !text-sm`} onClick={s.act.fn} disabled={busy}>
                  {s.act.label}<Icon name="arrow" size={16} />
                </button>
              )}
            </li>
          )
        })}
      </ol>
    </Panel>
  )
}

/** Screen 1: the station leader's three questions in five seconds. Are we safe? How much fuel? What is AURORA doing? */
export default function Overview({ d, go, tour, openHelp }: { d: O; go: (tab: string) => void; tour: Tour; openHelp: () => void }) {
  const f = d.fuel
  const score = f.survival_score
  const ls = d.live_savings
  const latest = d.alerts[0]
  const targets = d.station.storm_targets
  const ren = d.renewable_share_24h
  const t = d.loads.tiers
  const s = d.sources
  const daysToShip = Math.round((new Date(f.resupply).getTime() - new Date(d.time.replace(' ', 'T')).getTime()) / 864e5) + f.delay_days
  const futures = score === null ? null : Math.round(score * 100)
  const verdict = d.mode === 'fallback'
    ? { s: 'critical', t: 'The optimiser is unavailable, so the station is running on safe fixed rules until it recovers.' }
    : d.mode === 'storm' && d.storm
      ? { s: 'warning', t: `Blizzard expected${d.storm.hours_to_onset ? ` in ${d.storm.hours_to_onset.toFixed(0)} hours` : ' now'}. AURORA is filling the battery and heat tank and keeping a generator ready.` }
      : f.level === 'critical' || f.level === 'warning'
        ? { s: f.level, t: f.level === 'critical' ? `Fuel is likely to run short before the ship: it lasts in only ${futures} of 100 simulated futures. Open “Will fuel last?” for what to do.` : `Fuel is tight: it lasts until the ship in ${futures} of 100 simulated futures. See what to do on “Will fuel last?”.` }
        : { s: 'ok', t: `All normal. Fuel lasts until the ship in ${futures ?? '…'} of 100 simulated futures, and AURORA is running the station on less diesel than today’s rules.` }
  const running = d.gens.filter((g) => g.on)

  return (
    <>
      <PageHeader step="Step 1 of 5 · Station now" title="Is the station OK right now?"
        question="Safety, fuel and power at a glance. AURORA re-plans every 15 minutes; this page updates live."
        actions={<button className="btn hidden lg:inline-flex" onClick={openHelp}><Icon name="help" size={17} />How AURORA works</button>}>
        <Verdict status={verdict.s}>{verdict.t}</Verdict>
      </PageHeader>

      {!tour.hidden && <GettingStarted tour={tour} go={go} />}

      {d.mode === 'storm' && d.storm && (
        <Panel title={d.storm.hours_to_onset ? `Blizzard in ${d.storm.hours_to_onset.toFixed(0)} h · ${Math.round(100 * d.storm.prob_max)}% likely` : 'Blizzard in progress'}
          sub="Storm Mode prepares the station before the wind arrives." icon={<IconBadge name="blizzard" color="var(--warning)" />}
          style={{ borderColor: 'color-mix(in srgb, var(--warning) 45%, white)', background: 'linear-gradient(180deg, var(--warning-soft), #fff 60%)' }}>
          <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
            {targets && [
              { label: 'Charge battery', now: d.storage.soc, to: targets.soc, color: SERIES.battery, icon: 'battery' },
              { label: 'Pre-heat heat tank', now: d.storage.tank_soc, to: targets.tank, color: SERIES.heat, icon: 'tank' },
            ].map((x) => {
              const ok = x.now >= x.to - 0.01
              return (
                <div key={x.label} className="tile p-3.5">
                  <div className="flex items-center gap-2 font-semibold"><span style={{ color: x.color }}><Icon name={x.icon} size={17} /></span>{x.label}
                    {ok && <span className="ml-auto" style={{ color: 'var(--good)' }}><Icon name="done" size={17} /></span>}</div>
                  <div className="num text-sm mt-1" style={{ color: 'var(--ink-2)' }}>{fmt.pct(x.now)} now · target {fmt.pct(x.to)}</div>
                  <div className="mt-2"><Bar value={x.now} color={x.color} height={8} marker={x.to} markerLabel="Storm target" /></div>
                </div>
              )
            })}
            <div className="tile p-3.5">
              <div className="flex items-center gap-2 font-semibold"><span style={{ color: SERIES.diesel }}><Icon name="generator" size={17} /></span>Standby generator</div>
              <div className="text-sm mt-1" style={{ color: 'var(--ink-2)' }}>{running.length ? `${running.map((g) => g.id).join(', ')} online and ready` : 'Starts one hour before the storm'}</div>
            </div>
            <div className="tile p-3.5">
              <div className="flex items-center gap-2 font-semibold"><span style={{ color: SERIES.wind }}><Icon name="wind" size={17} /></span>Wind turbines</div>
              <div className="text-sm mt-1" style={{ color: 'var(--ink-2)' }}>{s.turbines_on ? 'Running; parked before wind gets unsafe' : 'Parked: wind is too strong'}</div>
            </div>
          </div>
        </Panel>
      )}

      {d.events.length > 0 && d.events[0].message && (
        <Callout status="info"><b>Latest event</b> <span className="num" style={{ color: 'var(--muted)' }}>· {fmt.time(d.events[0].time)}</span> · {d.events[0].message}</Callout>
      )}

      <div className="grid gap-5 grid-cols-1 sm:grid-cols-2 xl:grid-cols-4">
        <Kpi label="Fuel survival score" icon="shield" color={f.level === 'ok' ? 'var(--good)' : 'var(--warning)'}
          value={score === null ? '…' : Math.round(score * 100)} unit="%"
          note={score === null ? 'Running 1,000 scenarios…' : `Fuel lasts until the ship in ${futures} of 100 futures`} />
        <Kpi label="Fuel on station" icon="fuel" color={SERIES.diesel} value={(f.level_l / 1000).toFixed(1)} unit="kL"
          note={`${fmt.pct(f.level_l / f.capacity_l)} of tank · ship in ${daysToShip} days`} />
        <Kpi label="Diesel saved so far" icon="saving" color="var(--accent)" tone="var(--accent)" value={Math.round(ls.saved_l).toLocaleString('en-IN')} unit="L"
          note={`${ls.hours >= 12 ? `${ls.saved_pct.toFixed(0)}% less than today’s rules · ` : 'vs today’s rules · '}${ls.hours.toFixed(0)} h`} />
        <Kpi label="From sun and wind · 24 h" icon="solar" color={SERIES.solar} value={Math.round(ren * 100)} unit="%"
          note="of electricity and heat delivered" />
      </div>

      <Panel title="Where the power is going right now" icon={<IconBadge name="bolt" color="var(--accent)" />}
          sub="Read left to right: sources feed the station's power line, which supplies the loads and charges storage. Thicker band = more power."
          right={<StatusChip status="ok" dot label="Live" />}>
          <div className="scroll-x"><div style={{ minWidth: 720, maxWidth: 1080, margin: '0 auto' }}>
            <Sankey busLabel={`${(s.gen_kw + s.pv_kw + s.wind_kw + Math.max(0, -s.batt_kw)).toFixed(0)} kW`}
              sources={[
                { key: 'pv', label: 'Solar', kw: s.pv_kw, color: SERIES.solar, icon: 'solar' },
                { key: 'wind', label: s.turbines_on ? 'Wind' : 'Wind (parked)', kw: s.wind_kw, color: SERIES.wind, icon: 'wind' },
                { key: 'gen', label: 'Diesel generators', kw: s.gen_kw, color: SERIES.diesel, icon: 'generator' },
                { key: 'bout', label: 'Battery', kw: Math.max(0, -s.batt_kw), color: SERIES.battery, icon: 'battery' },
              ]}
              sinks={[
                { key: 't1', label: 'Life support', kw: t['1'] + d.loads.water_kw, color: 'var(--t1)', icon: 'heart', note: 'Tier 1 · never cut' },
                { key: 't2', label: 'Comms & safety', kw: t['2'], color: 'var(--t2)', icon: 'comms' },
                { key: 't3', label: 'Science', kw: t['3'], color: 'var(--t3)', icon: 'science' },
                { key: 't4', label: 'Comfort & laundry', kw: t['4'] + d.loads.laundry_kw, color: 'var(--t4)', icon: 'comfort' },
                { key: 'bin', label: 'Charging battery', kw: Math.max(0, s.batt_kw), color: SERIES.battery, icon: 'battery' },
                { key: 'p2h', label: 'Surplus to heat', kw: d.loads.p2h_kw, color: SERIES.heat, icon: 'flame' },
              ]} />
          </div></div>
          <div className="mt-5 pt-5 grid gap-2" style={{ borderTop: '1px solid var(--line)' }}>
            <div className="flex items-center gap-2 font-semibold"><span style={{ color: SERIES.heat }}><Icon name="thermo" size={17} /></span>Heating circuit</div>
            <BalanceBars rows={[
              { label: 'Heat from', parts: [
                { label: 'Engine waste heat', kw: d.heat.recovered_kw - d.heat.dump_kw, color: '#fdba74', ink: '#7c2d12' },
                { label: 'Surplus power', kw: d.heat.p2h_kw, color: '#f9a8d4', ink: '#831843' },
                { label: 'Heat tank', kw: d.heat.tank_dis_kw, color: '#fbcfe8', ink: '#831843' },
                { label: 'Oil boiler', kw: d.heat.boiler_kw, color: '#c4b5fd', ink: '#3b0764' },
              ] },
              { label: 'Heat to', parts: [
                { label: 'Buildings', kw: d.heat.demand_kw, color: '#cbd5e1', ink: '#0f172a' },
                { label: 'Heat tank', kw: d.heat.tank_ch_kw, color: '#f9a8d4', ink: '#831843' },
              ] },
            ]} />
          </div>
        </Panel>

      <div className="grid gap-5 grid-cols-1 lg:grid-cols-3">
          <Panel title="What AURORA is doing" icon={<IconBadge name="spark" color="var(--accent)" />}>
            {d.plan_summary?.plan_fuel_l !== undefined ? (
              <div className="tile p-4">
                <div className="label">Next 48 hours</div>
                <div className="mt-1">Planned diesel <b className="num">{fmt.l(d.plan_summary.plan_fuel_l)}</b>, which is{' '}
                  <b className="num" style={{ color: 'var(--accent)' }}>{fmt.l(d.plan_summary.saving_l ?? 0)} less</b> than today's rules would burn.</div>
              </div>
            ) : <p className="m-0" style={{ color: 'var(--muted)' }}>Planning…</p>}
            {latest && (
              <div className="mt-3 rounded-xl p-4" style={{ background: latest.level === 'critical' ? 'var(--critical-soft)' : 'var(--warning-soft)' }}>
                <StatusChip status={latest.level} label={latest.title} />
                <p className="text-sm mt-2 mb-0" style={{ color: 'var(--ink-2)' }}>{latest.reason}</p>
              </div>
            )}
            <button className="btn w-full mt-3" onClick={() => go('decisions')}>See every decision<Icon name="arrow" size={16} /></button>
          </Panel>

          <Panel title="Generators" sub="Below 40% load a diesel engine wastes fuel and gums up (wet stacking).">
            <div className="grid gap-3.5">
              {d.gens.map((g) => (
                <div key={g.id}>
                  <div className="flex items-center justify-between text-sm mb-1.5">
                    <span className="font-semibold flex items-center gap-2"><span style={{ color: !g.available ? 'var(--critical)' : g.on ? SERIES.diesel : 'var(--muted)' }}><Icon name="generator" size={16} /></span>{g.id}</span>
                    <span className="num" style={{ color: !g.available ? 'var(--critical)' : 'var(--ink-2)' }}>
                      {!g.available ? 'Tripped (fault)' : g.on ? `${g.kw.toFixed(0)} kW · ${g.loading_pct}% load` : 'Off, ready'}
                    </span>
                  </div>
                  <div className="relative">
                    <Bar value={g.on ? g.loading_pct : 0} max={100} height={10}
                      color={!g.available ? 'var(--critical)' : g.loading_pct < 40 ? 'var(--warning)' : SERIES.diesel} />
                    <div className="absolute top-0 bottom-0" title="40% minimum healthy load" style={{ left: '40%', borderLeft: '2px dashed var(--line-2)' }} />
                  </div>
                </div>
              ))}
            </div>
          </Panel>

        <Panel title="Will the fuel last until the ship?" sub="Each dot is one simulated future of weather, demand and ship delay."
          right={f.level ? <StatusChip status={f.level} /> : undefined}>
          {score === null ? <p style={{ color: 'var(--muted)' }}>Running 1,000 scenarios…</p> : (
            <>
              <FutureDots share={score} />
              <p className="mt-3 mb-0 text-sm" style={{ color: 'var(--ink-2)' }}>
                <b style={{ color: 'var(--good)' }}>Green</b>: fuel stays above the {fmt.kl(f.reserve_l)} safety reserve until the ship.
                {f.survival_score_diesel_first !== null && <> With today's rules: <b className="num">{Math.round(f.survival_score_diesel_first * 100)} of 100</b>.</>}
              </p>
            </>
          )}
          <button className="btn w-full mt-4" onClick={() => go('fuel')}>Fuel and resupply details<Icon name="arrow" size={16} /></button>
        </Panel>

      </div>

      <div className="grid gap-5 grid-cols-1 lg:grid-cols-2">
        <Panel title="Energy stores" sub="Stored energy lets AURORA switch generators off.">
          <div className="grid gap-4">
            {[
              { label: 'Battery', icon: 'battery', v: d.storage.soc, c: SERIES.battery, kwh: d.station.battery_kwh, target: d.mode === 'storm' ? targets?.soc : undefined },
              { label: 'Heat tank', icon: 'tank', v: d.storage.tank_soc, c: SERIES.heat, kwh: d.station.tank_kwh, target: d.mode === 'storm' ? targets?.tank : undefined },
            ].map((x) => (
              <div key={x.label}>
                <div className="flex items-baseline justify-between">
                  <span className="font-semibold flex items-center gap-2"><span style={{ color: x.c }}><Icon name={x.icon} size={17} /></span>{x.label}</span>
                  <span><span className="big text-2xl">{Math.round(x.v * 100)}</span><span className="unit text-2xl">%</span></span>
                </div>
                <div className="mt-1.5"><Bar value={x.v} color={x.c} height={12} marker={x.target} markerLabel="Storm target" /></div>
                <div className="text-xs mt-1" style={{ color: 'var(--muted)' }}>{Math.round(x.v * x.kwh)} of {x.kwh} kWh{x.target ? ` · storm target ${fmt.pct(x.target)}` : ''}</div>
              </div>
            ))}
          </div>
        </Panel>

        <Panel title="Energy mix, last 24 hours" sub="Share of electricity and heat delivered.">
          <SplitBar parts={[{ label: 'Sun and wind', value: ren, color: SERIES.wind, icon: 'wind' }, { label: 'Diesel', value: 1 - ren, color: SERIES.diesel, icon: 'fuel' }]} height={18} />
          <div className="grid grid-cols-2 gap-3 mt-5">
            <div className="tile p-3"><div className="label">Solar now</div><div className="big text-xl mt-1">{s.pv_kw.toFixed(0)}<span className="unit">kW</span></div></div>
            <div className="tile p-3"><div className="label">Wind now</div><div className="big text-xl mt-1">{s.wind_kw.toFixed(0)}<span className="unit">kW</span></div></div>
          </div>
          <div className="flex items-center gap-1.5 mt-3 text-[0.8125rem]" style={{ color: 'var(--good)' }}>
            <Icon name="leaf" size={15} />{(ls.co2_avoided_kg / 1000).toFixed(2)} t CO₂ avoided this run
          </div>
        </Panel>
      </div>

      {Object.keys(d.sensors).length > 0 && (
        <Panel title="Sensor quality" sub="Faulty readings are replaced with estimates, so control continues safely." icon={<IconBadge name="sensor" color="var(--warning)" />}>
          <div className="grid gap-2">
            {Object.entries(d.sensors).map(([m, fl]) => (
              <div key={m} className="flex justify-between items-center gap-2 text-sm"><span className="num">{m}</span><StatusChip status="warning" label={`${fl}, estimated`} /></div>
            ))}
          </div>
        </Panel>
      )}
    </>
  )
}
