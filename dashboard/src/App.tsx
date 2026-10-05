import { useCallback, useEffect, useState } from 'react'
import { notify, post, useLive, type Toast } from './api'
import { LIVE_APP_URL, STATIC } from './demo'
import { Icon, Logo } from './icons'
import Decisions from './screens/Decisions'
import Forecast from './screens/Forecast'
import Fuel from './screens/Fuel'
import Lab from './screens/Lab'
import Overview from './screens/Overview'
import { Empty, StatusChip } from './ui'

export const TABS = [
  { key: 'overview', label: 'Station now', hint: 'Is everything OK?', icon: 'overview' },
  { key: 'forecast', label: 'Next 48 hours', hint: "Weather and AURORA's plan", icon: 'forecast' },
  { key: 'decisions', label: 'Why AURORA acted', hint: 'Every action, explained', icon: 'decisions' },
  { key: 'fuel', label: 'Will fuel last?', hint: 'Until the supply ship', icon: 'fuel' },
  { key: 'lab', label: 'Try scenarios', hint: 'Blizzards, failures, a full year', icon: 'lab' },
]
const SPEEDS = [{ v: 1, label: '15 min' }, { v: 2, label: '30 min' }, { v: 4, label: '1 h' }, { v: 8, label: '2 h' }]

/** Getting-started progress, kept per browser. */
export type Tour = { done: Record<string, boolean>; mark: (k: string) => void; hidden: boolean; hide: (h: boolean) => void }
function useTour(): Tour {
  const read = <T,>(k: string, d: T): T => { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d } catch { return d } }
  const [done, setDone] = useState<Record<string, boolean>>(() => read('aurora-tour', {}))
  const [hidden, setHidden] = useState<boolean>(() => read('aurora-tour-hidden', false))
  const mark = useCallback((k: string) => setDone((d) => {
    if (d[k]) return d
    const n = { ...d, [k]: true }
    try { localStorage.setItem('aurora-tour', JSON.stringify(n)) } catch { /* private mode */ }
    return n
  }), [])
  const hide = (h: boolean) => { setHidden(h); try { localStorage.setItem('aurora-tour-hidden', JSON.stringify(h)) } catch { /* private mode */ } }
  return { done, mark, hidden, hide }
}

function HowItWorks({ onClose }: { onClose: () => void }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  const steps = [
    { icon: 'forecast', t: 'Forecast', d: 'Predicts weather, solar, wind and the station’s demand for the next 48 hours.' },
    { icon: 'spark', t: 'Plan', d: 'Chooses when to run each generator, charge the battery and store heat, to burn the least diesel.' },
    { icon: 'shield', t: 'Check', d: 'A safety guardrail checks every action. Life support is never switched off.' },
    { icon: 'fuel', t: 'Warn early', d: 'Tells the station leader, as a probability, whether fuel will last until the ship arrives.' },
  ]
  return (
    <div className="scrim" role="dialog" aria-modal="true" aria-labelledby="how-title" onClick={onClose}>
      <div className="card p-6 sm:p-8 max-w-[720px] w-full max-h-[90vh] overflow-auto rise" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-4">
          <div>
            <div className="eyebrow">The problem</div>
            <h2 id="how-title" className="text-2xl font-bold m-0 mt-1">Keeping a polar station alive on the least diesel</h2>
          </div>
          <button className="btn btn-ghost !min-h-[40px] !px-2.5" onClick={onClose} aria-label="Close"><Icon name="close" size={20} /></button>
        </div>
        <p className="mt-3" style={{ color: 'var(--ink-2)' }}>
          India’s Antarctic and Arctic stations run on diesel that arrives <b style={{ color: 'var(--ink)' }}>once a year by ship</b>. Heat, light, water and
          communications all depend on it. Running generators by fixed rules wastes fuel, and if fuel runs short before the ship, the crew is in danger.
        </p>
        <div className="eyebrow mt-5">What AURORA does, every 15 minutes</div>
        <ol className="grid sm:grid-cols-2 gap-3 mt-3 p-0 list-none">
          {steps.map((s, i) => (
            <li key={s.t} className="tile p-4 flex gap-3">
              <span className="badge" style={{ width: 36, height: 36, background: 'var(--accent-soft)', color: 'var(--accent)' }}><Icon name={s.icon} size={18} /></span>
              <div><div className="font-bold">{i + 1}. {s.t}</div><div className="text-sm" style={{ color: 'var(--ink-2)' }}>{s.d}</div></div>
            </li>
          ))}
        </ol>
        <div className="eyebrow mt-5">How to use this screen</div>
        <p className="mt-2 mb-0" style={{ color: 'var(--ink-2)' }}>
          Follow the menu from top to bottom. Each page answers one question. To see AURORA react, open <b style={{ color: 'var(--ink)' }}>Try scenarios</b> and start the blizzard demo.
        </p>
        <p className="text-xs mt-4 mb-0" style={{ color: 'var(--muted)' }}>Prototype for SIH PS 26061 (NCPOR, MoES). It runs on a digital twin with NASA POWER weather and synthetic loads, so every number is simulated.</p>
        <button className="btn btn-primary mt-5 w-full sm:w-auto" onClick={onClose}>Got it</button>
      </div>
    </div>
  )
}

export default function App() {
  const { data, connected } = useLive()
  const [tab, setTab] = useState(() => (TABS.some((t) => t.key === location.hash.slice(1)) ? location.hash.slice(1) : 'overview'))
  const [help, setHelp] = useState(() => { try { return !localStorage.getItem('aurora-seen-help') } catch { return false } })
  const tour = useTour()
  useEffect(() => { document.documentElement.dataset.theme = 'light' }, []) // light mode only
  useEffect(() => {
    history.replaceState(null, '', `#${tab}`); window.scrollTo({ top: 0 }); tour.mark(tab)
    document.querySelector('.nav [aria-current="page"]')?.scrollIntoView({ block: 'nearest', inline: 'nearest' }) // keep the active tab visible on phones
  }, [tab]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    const onHash = () => { const h = location.hash.slice(1); if (TABS.some((t) => t.key === h)) setTab(h) }
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const closeHelp = useCallback(() => { setHelp(false); try { localStorage.setItem('aurora-seen-help', '1') } catch { /* private mode */ } }, [])

  // Run/Pause and speed answer at once; the live feed confirms (or corrects) within a second or two
  const [want, setWant] = useState<{ running?: boolean; speed?: number }>({})
  const running = want.running ?? data?.running ?? false
  const speed = want.speed ?? data?.speed ?? 1
  useEffect(() => {
    if (!data) return
    setWant((w) => (w.running === data.running ? { ...w, running: undefined } : w))
    setWant((w) => (w.speed === data.speed ? { ...w, speed: undefined } : w))
  }, [data?.running, data?.speed]) // eslint-disable-line react-hooks/exhaustive-deps
  const control = (action: string, value?: number) => {
    if (action === 'play' || action === 'pause') setWant((w) => ({ ...w, running: action === 'play' }))
    if (action === 'speed') setWant((w) => ({ ...w, speed: value }))
    post('/api/sim/control', { action, value })
      .then(() => { if (action !== 'speed') notify(action === 'play' ? 'Simulation running' : 'Simulation paused', 'info') })
      .catch(() => setWant({}))
  }
  const [toasts, setToasts] = useState<Toast[]>([])
  useEffect(() => {
    const on = (e: Event) => {
      const t = (e as CustomEvent<Toast>).detail
      setToasts((ts) => [...ts.filter((x) => x.sticky).concat(ts.filter((x) => !x.sticky).slice(-2)), t])
      if (!t.sticky) window.setTimeout(() => setToasts((ts) => ts.filter((x) => x.id !== t.id)), t.status === 'critical' ? 9000 : 4500)
    }
    const off = (e: Event) => setToasts((ts) => ts.filter((x) => x.id !== (e as CustomEvent<number>).detail))
    window.addEventListener('aurora-toast', on)
    window.addEventListener('aurora-toast-dismiss', off)
    return () => { window.removeEventListener('aurora-toast', on); window.removeEventListener('aurora-toast-dismiss', off) }
  }, [])

  const step = data?.step ?? 0
  const hour = Math.floor(step / 4) // detail screens refresh once per simulated hour (or on their timer)
  const when = data?.ready ? new Date(data.time.replace(' ', 'T')) : null

  return (
    <div className="mx-auto max-w-[1600px] flex flex-wrap lg:flex-nowrap gap-5 p-3 sm:p-5">
      <aside className="card w-full lg:w-[284px] lg:flex-none lg:sticky lg:top-5 self-start p-3 sm:p-4 flex flex-col gap-1 min-w-0">
        <div className="flex items-center gap-2.5 px-2 pt-1 pb-3">
          <Logo size={36} />
          <div className="leading-tight">
            <div className="font-extrabold tracking-[0.04em]">AURORA</div>
            <div className="text-xs" style={{ color: 'var(--muted)' }}>Polar energy manager</div>
          </div>
          <button className="btn btn-ghost lg:hidden ml-auto !min-h-[40px] !px-3 !text-sm" onClick={() => setHelp(true)}>
            <Icon name="help" size={18} />How it works
          </button>
        </div>
        <nav aria-label="Screens" className="nav flex lg:flex-col gap-1 overflow-x-auto lg:overflow-visible -mx-1 px-1 pb-1 lg:pb-0">
          {TABS.map((t) => (
            <button key={t.key} className="nav-item" aria-current={tab === t.key ? 'page' : undefined} onClick={() => setTab(t.key)} title={t.hint}>
              <Icon name={t.icon} size={19} />
              <span className="whitespace-nowrap">{t.label}</span>
            </button>
          ))}
        </nav>
        <div className="hidden lg:block mt-auto pt-4">
          <button className="nav-item" onClick={() => setHelp(true)}><Icon name="help" size={19} />How AURORA works</button>
          <p className="text-xs px-3.5 mt-2 mb-1" style={{ color: 'var(--muted)' }}>Digital twin · all figures simulated</p>
        </div>
      </aside>

      <div className="flex-1 min-w-0 grid gap-5 content-start">
        <header className="card flex flex-wrap items-center gap-x-5 gap-y-3 px-5 py-3">
          <div className="min-w-0">
            <div className="font-bold">{data?.station ? `${data.station.name} Station` : 'AURORA'}</div>
            {data?.station && (
              <div className="text-xs" style={{ color: 'var(--muted)' }}>
                {data.station.location} · {Math.abs(data.station.lat).toFixed(2)}°{data.station.lat < 0 ? 'S' : 'N'}, {data.station.lon.toFixed(2)}°E
              </div>
            )}
          </div>
          {data?.ready && when && (
            <div className="flex items-center gap-2.5 tile px-3 py-1.5">
              <Icon name={data.weather.sun_up ? 'sun' : 'moon'} size={18} color={data.weather.sun_up ? 'var(--s-solar)' : 'var(--ink-2)'} />
              <div className="leading-tight">
                <div className="num text-sm font-semibold">{when.toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' })}, {when.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit' })}</div>
                <div className="text-xs" style={{ color: 'var(--muted)' }}>{data.weather.temp_c.toFixed(0)} °C · wind {data.weather.wind_ms.toFixed(0)} m/s</div>
              </div>
            </div>
          )}
          {data?.ready && <StatusChip status={data.mode} />}
          {data?.ready && !connected && <StatusChip status="warning" label="Reconnecting" />}
          {data?.ready && (
            <div className="ml-auto flex flex-wrap items-center gap-2.5">
              <span className="text-xs hidden xl:inline" style={{ color: 'var(--muted)' }}>Simulated time per second</span>
              <div className="seg" role="group" aria-label="Simulation speed: simulated time per real second">
                {SPEEDS.map((s) => <button key={s.v} aria-pressed={speed === s.v} onClick={() => control('speed', s.v)}>{s.label}</button>)}
              </div>
              <button className="btn btn-primary min-w-[104px]" onClick={() => control(running ? 'pause' : 'play')}>
                <Icon name={running ? 'pause' : 'play'} size={17} />{running ? 'Pause' : 'Run'}
              </button>
            </div>
          )}
        </header>

        {STATIC && (
          <div className="card px-5 py-3 flex flex-wrap items-center gap-x-4 gap-y-2" style={{ background: 'var(--accent-soft)', borderColor: 'color-mix(in srgb, var(--accent) 30%, white)' }}>
            <span style={{ color: 'var(--accent)' }}><Icon name="play" size={18} /></span>
            <span className="text-sm flex-1 min-w-[240px]"><b>Recorded demo.</b> You are watching real runs of the AURORA digital twin, replayed in your browser. All figures are simulated.</span>
            <a className="btn btn-accent !min-h-[40px] !text-sm" href={LIVE_APP_URL} target="_blank" rel="noreferrer">Run it live in Codespaces<Icon name="arrow" size={16} /></a>
          </div>
        )}
        <main className="grid gap-5 min-w-0">
          {!data?.ready ? <div className="card"><Empty>Starting the station twin and forecasters…</Empty></div> : (
            <>
              {tab === 'overview' && <Overview d={data} go={setTab} tour={tour} openHelp={() => setHelp(true)} />}
              {tab === 'forecast' && <Forecast step={hour} targets={data.station.storm_targets} stormActive={data.mode === 'storm'} go={setTab} />}
              {tab === 'decisions' && <Decisions step={hour} go={setTab} />}
              {tab === 'fuel' && <Fuel go={setTab} refreshKey={`${data.fuel.delay_days}|${data.fuel.survival_score}|${data.fuel.resupply}`} />}
              {tab === 'lab' && <Lab onInjected={(t) => { tour.mark('demo'); setTab(t) }} />}
            </>
          )}
        </main>
        <footer className="text-xs flex flex-wrap gap-x-5 gap-y-1 px-1 pb-2" style={{ color: 'var(--muted)' }}>
          <span>AURORA prototype · SIH PS 26061 · NCPOR, MoES</span>
          <span>Digital twin with NASA POWER weather and synthetic loads. All figures simulated.</span>
        </footer>
      </div>
      {help && <HowItWorks onClose={closeHelp} />}
      <div className="fixed z-[60] bottom-4 right-4 left-4 sm:left-auto grid gap-2 justify-items-end pointer-events-none" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className="card rise flex items-start gap-2.5 px-4 py-3 text-sm max-w-[420px] pointer-events-auto"
            style={{ borderColor: t.status === 'critical' ? 'var(--critical)' : 'var(--line-2)' }}>
            <span style={{ color: t.status === 'critical' ? 'var(--critical)' : t.status === 'ok' ? 'var(--good)' : 'var(--focus)', marginTop: 1 }}>
              {t.status === 'busy' ? <span className="spinner" /> : <Icon name={t.status === 'critical' ? 'alert' : 'done'} size={17} />}
            </span>
            <span>{t.text}</span>
          </div>
        ))}
      </div>
    </div>
  )
}
