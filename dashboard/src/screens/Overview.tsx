import type { Overview as O } from '../api'
import { fmt } from '../api'
import EnergyFlow from '../components/EnergyFlow'
import { Meter, Panel, SERIES, Stat, StatusChip } from '../ui'

/** Screen 1: the station leader's three questions in five seconds. Are we safe? How much fuel? What is AURORA doing? */
export default function Overview({ d, go }: { d: O; go: (tab: string) => void }) {
  const f = d.fuel
  const score = f.survival_score
  const scoreStatus = f.level ?? 'info'
  const ls = d.live_savings
  const latest = d.alerts[0]
  return (
    <div className="grid gap-4">
      {d.mode !== 'normal' && (
        <div className="panel p-4 flex flex-wrap items-center gap-3" role="alert"
          style={{ borderColor: d.mode === 'storm' ? 'var(--warning)' : 'var(--critical)' }}>
          <StatusChip status={d.mode} />
          <span className="font-medium">
            {d.mode === 'storm' ? d.storm?.message : 'Optimiser unavailable: station on safe diesel-first rules.'}
          </span>
        </div>
      )}

      <div className="grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-4">
        <Panel>
          <div className="flex items-start justify-between gap-2">
            <Stat big label="Fuel Survival Score" value={score === null ? '…' : fmt.pct(score)}
              sub={`Chance fuel stays above the ${fmt.kl(f.reserve_l)} reserve until the ship arrives`} />
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <StatusChip status={scoreStatus} />
            {f.survival_score_diesel_first !== null && (
              <span className="text-sm" style={{ color: 'var(--ink-2)' }}>Diesel-first: {fmt.pct(f.survival_score_diesel_first)}</span>
            )}
          </div>
          <button className="btn mt-3 w-full" onClick={() => go('fuel')}>Fuel and resupply →</button>
        </Panel>

        <Panel>
          <Stat label="Fuel on station" value={fmt.kl(f.level_l)}
            sub={`Resupply ${fmt.date(f.resupply)}${f.delay_days ? ` + ${f.delay_days} d delay` : ''}`} />
          <div className="mt-4">
            <Meter value={f.level_l} max={f.capacity_l} marker={f.reserve_l}
              color={f.level_l < f.reserve_l ? 'var(--critical)' : 'var(--s-diesel)'} height={14} />
            <div className="flex justify-between text-xs mt-1 num" style={{ color: 'var(--muted)' }}>
              <span>0</span><span>reserve {fmt.kl(f.reserve_l)}</span><span>{fmt.kl(f.capacity_l)}</span>
            </div>
          </div>
        </Panel>

        <Panel>
          <Stat label="Renewable share, last 24 h" value={fmt.pct(d.renewable_share_24h)} sub="of electricity and heat delivered" />
          <div className="mt-4 grid grid-cols-2 gap-3">
            <Stat label="Battery" value={fmt.pct(d.storage.soc)} />
            <Stat label="Thermal tank" value={fmt.pct(d.storage.tank_soc)} />
          </div>
        </Panel>

        <Panel>
          <Stat label="Saved vs diesel-first" value={fmt.l(ls.saved_l)}
            sub={`${ls.hours >= 12 ? `${ls.saved_pct.toFixed(1)}% less over ` : 'over '}${ls.hours.toFixed(0)} h · ${(ls.co2_avoided_kg / 1000).toFixed(2)} t CO₂ avoided`} />
          <div className="mt-3 text-sm" style={{ color: 'var(--ink-2)' }}>
            A shadow station running today's rules sees the same weather and events. <span className="label">Simulated</span>
          </div>
        </Panel>
      </div>

      <div className="grid gap-4 grid-cols-1 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel title="Live energy flow" sub="Where every kilowatt is coming from and going to right now"
          right={<span className="num text-sm" style={{ color: 'var(--ink-2)' }}>{d.weather.temp_c.toFixed(1)} °C · wind {d.weather.wind_ms.toFixed(1)} m/s · {d.weather.sun_up ? 'sun up' : 'no sun'}</span>}>
          <div className="overflow-x-auto"><div style={{ minWidth: 640 }}><EnergyFlow d={d} /></div></div>
        </Panel>

        <div className="grid gap-4 content-start">
          <Panel title="What AURORA is doing">
            {d.plan_summary?.plan_fuel_l !== undefined ? (
              <div className="grid gap-2">
                <p>Next 48 h plan burns <b className="num">{fmt.l(d.plan_summary.plan_fuel_l)}</b>,{' '}
                  <b className="num">{fmt.l(d.plan_summary.saving_l ?? 0)}</b> less than diesel-first rules on the same forecast.</p>
                {(d.plan_summary.drivers ?? []).length > 0 && (
                  <ul className="text-sm grid gap-1" style={{ color: 'var(--ink-2)' }}>
                    {d.plan_summary.drivers!.map((x) => <li key={x}>• Load {x}</li>)}
                  </ul>
                )}
              </div>
            ) : <p style={{ color: 'var(--muted)' }}>Planning…</p>}
            {latest && (
              <div className="mt-3 rounded-lg p-3" style={{ background: 'var(--surface-2)' }}>
                <div className="flex items-center gap-2"><StatusChip status={latest.level} label={latest.title} /></div>
                <p className="text-sm mt-2">{latest.reason}</p>
              </div>
            )}
            <button className="btn mt-3 w-full" onClick={() => go('decisions')}>All decisions →</button>
          </Panel>

          <Panel title="Generators">
            <div className="grid gap-3">
              {d.gens.map((g) => (
                <div key={g.id} className="grid grid-cols-[40px_1fr_70px] items-center gap-2">
                  <span className="font-display font-semibold">{g.id}</span>
                  <Meter value={g.on ? g.loading_pct : 0} max={100} marker={40}
                    color={!g.available ? 'var(--critical)' : g.loading_pct < 40 ? 'var(--warning)' : SERIES.diesel} />
                  <span className="num text-sm text-right">{!g.available ? 'TRIP' : g.on ? `${g.loading_pct}%` : 'off'}</span>
                </div>
              ))}
              <p className="text-xs" style={{ color: 'var(--muted)' }}>Marker at 40%: below it diesels wet-stack and waste fuel.</p>
            </div>
          </Panel>

          {Object.keys(d.sensors).length > 0 && (
            <Panel title="Sensor quality">
              {Object.entries(d.sensors).map(([m, f]) => (
                <div key={m} className="flex justify-between text-sm"><span className="num">{m}</span><StatusChip status="warning" label={`${f}, imputed`} /></div>
              ))}
            </Panel>
          )}
        </div>
      </div>
    </div>
  )
}
