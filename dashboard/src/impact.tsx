import { useEffect, useState } from 'react'
import type { Overview } from './api'
import { fmt } from './api'
import { Icon } from './icons'

/** After an injected event or a demo, show exactly what changed: what should happen (ticked off as it
 *  happens), the key numbers before and now, and where to look. Works for live and recorded demos. */

export type Impact = { kind: string; label: string; message: string; before: Overview | null; at: number; tab?: string }

/** Lab calls these around a scenario request. Arm before the request (snapshot "before" on the client, used when
 *  the server does not send one), then confirm with the server's answer. */
export function armImpact() { window.dispatchEvent(new CustomEvent('aurora-impact-arm')) }
export function confirmImpact(kind: string, label: string, message: string, before?: Overview | null, tab?: string) {
  window.dispatchEvent(new CustomEvent('aurora-impact', { detail: { kind, label, message, before: before ?? null, tab } }))
}

type Check = { text: string; state: 'done' | 'active' | 'waiting' | 'info'; detail?: string }
const pct = (v: number) => `${Math.round(100 * v)}%`
const kw = (v: number) => `${Math.round(v)} kW`
const online = (d: Overview) => d.gens.filter((g) => g.on).length
const tripped = (d: Overview) => d.gens.filter((g) => !g.available).map((g) => g.id)

function checks(kind: string, b: Overview, n: Overview, seen: Set<string>): Check[] {
  const lifeOk: Check = n.loads.unserved_kw > 0.5
    ? { text: 'Life support stays powered', state: 'active', detail: `${kw(n.loads.unserved_kw)} short right now` }
    : { text: 'Life support stays powered', state: 'done', detail: 'nothing switched off' }
  const tg = n.station.storm_targets ?? { soc: 0.85, tank: 0.8 }
  const far = (n.storm?.hours_to_onset ?? 0) > 6
  const rising = (x: number, y: number, target: number, what: string): Check =>
    y >= target - 0.03 ? { text: `${what} reaches ${pct(target)}`, state: 'done', detail: `${pct(x)} → ${pct(y)}` }
      : { text: `${what} fills toward ${pct(target)}`, state: y > x + 0.01 ? 'active' : 'waiting',
          detail: `${pct(x)} → ${pct(y)}${y <= x + 0.01 && far ? ' · AURORA fills it in the last hours before the storm (ready 3 h early), not now' : ''}` }
  switch (kind) {
    case 'blizzard': {
      const parked = !n.sources.turbines_on
      return [
        n.mode === 'storm' || seen.has('storm')
          ? { text: 'Storm Mode switches on', state: 'done', detail: n.storm?.hours_to_onset != null && n.storm.hours_to_onset > 0 ? `blizzard in about ${Math.round(n.storm.hours_to_onset)} h` : 'blizzard has arrived' }
          : { text: 'Storm Mode switches on', state: 'waiting', detail: 'at the next plan (within 15 simulated minutes)' },
        rising(b.storage.soc, n.storage.soc, tg.soc, 'Battery'),
        rising(b.storage.tank_soc, n.storage.tank_soc, tg.tank, 'Heat tank'),
        online(n) > 0 ? { text: 'A standby generator stays online', state: 'done', detail: `${online(n)} running` }
          : { text: 'A standby generator stays online', state: 'waiting', detail: 'from an hour before the storm' },
        parked || seen.has('parked') ? { text: 'Wind turbines park before the wind gets unsafe', state: 'done', detail: `hub wind ${Math.round(n.weather.hub_wind_ms)} m/s` }
          : { text: 'Wind turbines park before the wind gets unsafe', state: 'waiting', detail: `parks at about 24 m/s; now ${Math.round(n.weather.hub_wind_ms)} m/s` },
        lifeOk,
      ]
    }
    case 'generator_failure': {
      const newTrip = tripped(n).filter((g) => !tripped(b).includes(g))
      const wasRunning = b.gens.some((g) => newTrip.includes(g.id) && g.on)
      return [
        newTrip.length ? { text: `${newTrip.join(', ')} goes offline (TRIP)`, state: 'done', detail: 'shown in red on Station now' }
          : { text: 'A generator goes offline (TRIP)', state: tripped(n).length ? 'done' : 'waiting', detail: tripped(n).join(', ') || '' },
        wasRunning
          ? { text: 'Battery covers the gap at once; another unit starts if needed', state: 'done', detail: `${online(n)} running · battery ${pct(n.storage.soc)}` }
          : { text: 'Nothing else has to change: the unit was on standby', state: 'done', detail: `one fewer spare unit · ${online(n)} running` },
        lifeOk,
        wasRunning ? { text: 'A warning card explains what happened', state: 'info', detail: 'see Why AURORA acted' }
          : { text: 'Tip: trip a generator while one is running to see AURORA react', state: 'info', detail: 'run the simulation until a unit shows a load %' },
      ]
    }
    case 'resupply_delay': {
      const bs = b.fuel.survival_score, ns = n.fuel.survival_score
      return [
        { text: 'The ship arrives later', state: n.fuel.delay_days > b.fuel.delay_days ? 'done' : 'waiting', detail: `delay ${b.fuel.delay_days} → ${n.fuel.delay_days} days` },
        ns == null || bs == null ? { text: 'Fuel Survival Score is re-scored', state: 'active', detail: 'running 1,000 futures…' }
          : { text: 'Fuel Survival Score is re-scored', state: 'done', detail: `${pct(bs)} → ${pct(ns)}` },
        { text: 'Ranked fuel-saving actions appear', state: 'info', detail: 'see Will fuel last?' },
      ]
    }
    case 'wind_surplus':
      return [
        { text: 'Strong, steady wind', state: n.sources.wind_avail_kw > b.sources.wind_avail_kw + 1 ? 'done' : 'waiting', detail: `wind power ${kw(b.sources.wind_avail_kw)} → ${kw(n.sources.wind_avail_kw)}` },
        { text: 'Surplus is stored, not wasted', state: n.sources.curtail_kw < 5 ? 'done' : 'active', detail: `curtailed ${kw(n.sources.curtail_kw)} · battery ${pct(n.storage.soc)} · heat tank ${pct(n.storage.tank_soc)}` },
        { text: 'Generators burn less', state: n.sources.gen_kw < b.sources.gen_kw - 1 ? 'done' : 'waiting', detail: `generators ${kw(b.sources.gen_kw)} → ${kw(n.sources.gen_kw)}` },
      ]
    case 'sensor_loss': {
      const flagged = Object.entries(n.sensors)
      return [
        flagged.length ? { text: 'The frozen sensor is detected', state: 'done', detail: flagged.map(([m, f]) => `${m}: ${f}`).join(', ') }
          : { text: 'The frozen sensor is detected', state: 'waiting', detail: 'after about 20 identical readings (20 minutes)' },
        { text: 'AURORA uses an estimate and widens its safety reserve', state: flagged.length ? 'done' : 'waiting' },
        lifeOk,
      ]
    }
    case 'fuel_leak': {
      const drop = b.fuel.level_l - n.fuel.level_l
      const burned = n.live_savings.aurora_fuel_l - b.live_savings.aurora_fuel_l
      return [
        { text: 'Fuel on station drops faster than the generators burn', state: drop - burned > 50 ? 'done' : 'waiting',
          detail: `−${fmt.l(drop)} in total, of which about ${fmt.l(Math.max(0, drop - burned))} is the leak` },
        { text: 'Fuel Survival Score is re-scored', state: 'info', detail: n.fuel.survival_score != null ? `now ${pct(n.fuel.survival_score)}` : '' },
      ]
    }
    case 'optimizer_failure':
      return [
        seen.has('fallback') ? { text: 'Station switches to safe fallback rules', state: 'done', detail: 'today’s diesel-first rules take over' }
          : { text: 'Station switches to safe fallback rules', state: 'waiting', detail: 'at the next step' },
        seen.has('fallback') && n.mode !== 'fallback' ? { text: 'AURORA takes back control', state: 'done', detail: 'after 2 simulated hours' }
          : { text: 'AURORA takes back control', state: 'waiting', detail: 'after 2 simulated hours' },
        lifeOk,
      ]
    default:
      return [lifeOk]
  }
}

type Row = { key: string; label: string; icon: string; b: string; n: string; changed: boolean; good?: boolean }
function rows(b: Overview, n: Overview): Row[] {
  const r = (key: string, label: string, icon: string, bv: number | string, nv: number | string, f: (v: number) => string, eps: number, upGood?: boolean): Row => {
    const changed = typeof bv === 'number' && typeof nv === 'number' ? Math.abs(nv - bv) > eps : bv !== nv
    const good = typeof bv === 'number' && typeof nv === 'number' && upGood !== undefined ? (nv > bv) === upGood : undefined
    return { key, label, icon, b: typeof bv === 'number' ? f(bv) : bv, n: typeof nv === 'number' ? f(nv) : nv, changed, good: changed ? good : undefined }
  }
  const gens = (d: Overview) => d.gens.map((g) => `${g.id} ${!g.available ? 'TRIP' : g.on ? `${g.loading_pct}%` : 'off'}`).join(' · ')
  const mode = (d: Overview) => ({ normal: 'Normal', storm: 'Storm Mode', fallback: 'Fallback rules' })[d.mode]
  const score = (d: Overview) => (d.fuel.survival_score == null ? '…' : pct(d.fuel.survival_score))
  const ship = (d: Overview) => `${fmt.date(d.fuel.resupply)}${d.fuel.delay_days ? ` + ${d.fuel.delay_days} d` : ''}`
  return [
    r('mode', 'Mode', 'shield', mode(b), mode(n), String, 0),
    r('gens', 'Generators', 'generator', gens(b), gens(n), String, 0),
    r('gen_kw', 'Generator output', 'generator', b.sources.gen_kw, n.sources.gen_kw, kw, 5),
    r('soc', 'Battery', 'battery', b.storage.soc, n.storage.soc, pct, 0.02),
    r('tank', 'Heat tank', 'tank', b.storage.tank_soc, n.storage.tank_soc, pct, 0.02),
    r('wind', 'Wind power', 'wind', b.sources.wind_kw, n.sources.wind_kw, kw, 3),
    r('solar', 'Solar power', 'solar', b.sources.pv_kw, n.sources.pv_kw, kw, 3),
    r('curt', 'Renewables wasted', 'leaf', b.sources.curtail_kw, n.sources.curtail_kw, kw, 3, false),
    r('turb', 'Wind turbines', 'wind', b.sources.turbines_on ? 'running' : 'parked', n.sources.turbines_on ? 'running' : 'parked', String, 0),
    r('fuel', 'Fuel on station', 'fuel', b.fuel.level_l, n.fuel.level_l, (v) => `${(v / 1000).toFixed(1)} kL`, 50),
    r('score', 'Fuel Survival Score', 'target', score(b), score(n), String, 0),
    r('ship', 'Ship arrives', 'ship', ship(b), ship(n), String, 0),
    r('life', 'Life support cut', 'heart', b.loads.unserved_kw, n.loads.unserved_kw, kw, 0.5, false),
    r('sensors', 'Sensor problems', 'sensor', Object.keys(b.sensors).length ? Object.keys(b.sensors).join(', ') : 'none',
      Object.keys(n.sensors).length ? Object.entries(n.sensors).map(([m, f]) => `${m} ${f}`).join(', ') : 'none', String, 0),
  ]
}

const FIRST: Record<string, string[]> = {
  blizzard: ['mode', 'soc', 'tank', 'gens', 'turb', 'wind', 'life'],
  generator_failure: ['gens', 'gen_kw', 'soc', 'life', 'mode'],
  resupply_delay: ['ship', 'score', 'fuel'],
  wind_surplus: ['wind', 'curt', 'soc', 'tank', 'gen_kw', 'gens'],
  sensor_loss: ['sensors', 'mode', 'gens', 'life'],
  fuel_leak: ['fuel', 'score', 'gen_kw'],
  optimizer_failure: ['mode', 'gens', 'life'],
}
const WHERE: Record<string, { tab: string; label: string }[]> = {
  blizzard: [{ tab: 'forecast', label: 'Next 48 hours' }, { tab: 'decisions', label: 'Why AURORA acted' }],
  generator_failure: [{ tab: 'overview', label: 'Station now' }, { tab: 'decisions', label: 'Why AURORA acted' }],
  resupply_delay: [{ tab: 'fuel', label: 'Will fuel last?' }],
  wind_surplus: [{ tab: 'overview', label: 'Station now' }, { tab: 'forecast', label: 'Next 48 hours' }],
  sensor_loss: [{ tab: 'overview', label: 'Station now' }],
  fuel_leak: [{ tab: 'fuel', label: 'Will fuel last?' }],
  optimizer_failure: [{ tab: 'decisions', label: 'Why AURORA acted' }],
}
const STATE_ICON = { done: { icon: 'done', color: 'var(--good)', label: 'Done' }, active: { icon: 'activity', color: 'var(--warning)', label: 'In progress' },
  waiting: { icon: 'clock', color: 'var(--muted)', label: 'Waiting' }, info: { icon: 'arrow', color: 'var(--focus)', label: 'Look here' } }

export function EventImpact({ impact, now, onClose, go }: { impact: Impact; now: Overview; onClose: () => void; go: (tab: string) => void }) {
  const [open, setOpen] = useState(true)
  const [seen, setSeen] = useState<Set<string>>(new Set())
  useEffect(() => { setOpen(true); setSeen(new Set()) }, [impact.at])
  useEffect(() => { // remember states that only last a while (fallback, Storm Mode, parked turbines)
    setSeen((s) => {
      const add = [now.mode === 'fallback' && 'fallback', now.mode === 'storm' && 'storm', !now.sources.turbines_on && 'parked'].filter(Boolean) as string[]
      return add.every((a) => s.has(a)) ? s : new Set([...s, ...add])
    })
  }, [now.mode, now.sources.turbines_on])

  const b = impact.before
  const hours = b ? Math.max(0, (new Date(now.time.replace(' ', 'T')).getTime() - new Date(b.time.replace(' ', 'T')).getTime()) / 3.6e6) : 0
  const list = b ? checks(impact.kind, b, now, seen) : []
  const all = b ? rows(b, now) : []
  const order = FIRST[impact.kind] ?? []
  const table = [...all.filter((r) => order.includes(r.key)).sort((x, y) => order.indexOf(x.key) - order.indexOf(y.key)),
    ...all.filter((r) => !order.includes(r.key) && r.changed)]
  const changedCount = all.filter((r) => r.changed).length
  const dA = b ? now.live_savings.aurora_fuel_l - b.live_savings.aurora_fuel_l : 0
  const dB = b ? now.live_savings.diesel_first_fuel_l - b.live_savings.diesel_first_fuel_l : 0

  return (
    <section className="card rise p-4 sm:p-5" aria-labelledby="impact-title" style={{ borderColor: 'var(--accent)', borderWidth: 2 }}>
      <div className="flex flex-wrap items-start gap-3">
        <span className="badge" style={{ width: 40, height: 40, background: 'var(--accent-soft)', color: 'var(--accent)' }}><Icon name="activity" size={20} /></span>
        <div className="min-w-0 flex-1">
          <div className="eyebrow">Event impact · {hours < 0.1 ? 'just now' : `${hours.toFixed(hours < 10 ? 1 : 0)} simulated hours ago`}</div>
          <h2 id="impact-title" className="text-lg font-bold m-0 mt-0.5">What changed after: {impact.label}</h2>
          <p className="text-sm m-0 mt-0.5" style={{ color: 'var(--ink-2)' }}>{impact.message}{b ? ` · ${changedCount} of ${all.length} readings changed` : ''}</p>
        </div>
        <div className="flex gap-2 ml-auto">
          <button className="btn btn-ghost !min-h-[40px] !px-3 !text-sm" onClick={() => setOpen((o) => !o)} aria-expanded={open}>{open ? 'Hide details' : 'Show details'}</button>
          <button className="btn btn-ghost !min-h-[40px] !px-2.5" onClick={onClose} aria-label="Close event impact"><Icon name="close" size={18} /></button>
        </div>
      </div>

      {open && (b ? (
        <div className="grid gap-4 mt-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)]">
          <div className="min-w-0">
            <div className="text-sm font-bold mb-2">What should happen</div>
            <ol className="grid gap-2 p-0 m-0 list-none">
              {list.map((c) => {
                const s = STATE_ICON[c.state]
                return (
                  <li key={c.text} className="tile px-3 py-2.5 flex gap-2.5 items-start">
                    <span style={{ color: s.color, marginTop: 2 }} title={s.label}><Icon name={s.icon} size={18} /></span>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold">{c.text}<span className="sr-only"> ({s.label})</span></div>
                      {c.detail && <div className="text-xs num" style={{ color: 'var(--ink-2)' }}>{c.detail}</div>}
                    </div>
                  </li>
                )
              })}
            </ol>
            <div className="tile px-3 py-2.5 mt-2 text-sm">
              <div className="font-semibold">Diesel burned since the event</div>
              <div className="num text-xs mt-0.5" style={{ color: 'var(--ink-2)' }}>
                AURORA {fmt.l(dA)} · today’s rules {fmt.l(dB)}{dB > dA + 0.5 ? ` · ${fmt.l(dB - dA)} saved` : ''}
              </div>
            </div>
            <div className="flex flex-wrap gap-2 mt-3">
              {(WHERE[impact.kind] ?? []).map((w) => (
                <button key={w.tab} className="btn !min-h-[40px] !text-sm" onClick={() => go(w.tab)}>See it on “{w.label}”<Icon name="arrow" size={16} /></button>
              ))}
            </div>
          </div>
          <div className="min-w-0 overflow-x-auto">
            <table className="w-full text-sm" style={{ minWidth: 420 }}>
              <caption className="text-left text-sm font-bold mb-2">Before → now <span className="font-normal text-xs" style={{ color: 'var(--muted)' }}>(highlighted rows changed)</span></caption>
              <thead><tr className="text-xs text-left" style={{ color: 'var(--muted)' }}><th className="py-1 pr-2 font-semibold">Reading</th><th className="py-1 pr-2 font-semibold">Before</th><th className="py-1 font-semibold">Now</th></tr></thead>
              <tbody>
                {table.map((r) => (
                  <tr key={r.key} style={{ background: r.changed ? 'var(--accent-soft)' : undefined, borderTop: '1px solid var(--line)' }}>
                    <td className="py-1.5 pl-1.5 pr-2 whitespace-nowrap"><span className="inline-flex items-center gap-1.5"><Icon name={r.icon} size={15} color="var(--ink-2)" />{r.label}</span></td>
                    <td className="py-1.5 pr-2 num" style={{ color: 'var(--ink-2)' }}>{r.b}</td>
                    <td className="py-1.5 pr-1.5 num font-semibold">
                      {r.n}{r.changed && <span className="ml-1.5 text-xs font-bold" style={{ color: r.good === undefined ? 'var(--accent)' : r.good ? 'var(--good)' : 'var(--critical)' }}>
                        {r.good === undefined ? '● changed' : r.good ? '▲ better' : '▼ worse'}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : (
        <p className="text-sm mt-3 mb-0" style={{ color: 'var(--ink-2)' }}>The station was reset to a clean state. Inject an event to see what it changes.</p>
      ))}
    </section>
  )
}
