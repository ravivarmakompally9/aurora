import { useEffect, useState } from 'react'
import { fmt, post, useLive } from './api'
import Decisions from './screens/Decisions'
import Forecast from './screens/Forecast'
import Fuel from './screens/Fuel'
import Lab from './screens/Lab'
import Overview from './screens/Overview'
import { Empty, StatusChip } from './ui'

const TABS = [
  { key: 'overview', label: 'Overview' },
  { key: 'forecast', label: 'Forecast & plan' },
  { key: 'decisions', label: 'Decisions' },
  { key: 'fuel', label: 'Fuel & resupply' },
  { key: 'lab', label: 'Simulation lab' },
]

export default function App() {
  const { data, connected } = useLive()
  const [tab, setTab] = useState(() => (TABS.some((t) => t.key === location.hash.slice(1)) ? location.hash.slice(1) : 'overview'))
  const [theme, setTheme] = useState<'dark' | 'light'>(() => (localStorage.getItem('aurora-theme') as 'dark' | 'light') ?? 'dark')
  useEffect(() => { document.documentElement.dataset.theme = theme; localStorage.setItem('aurora-theme', theme) }, [theme])
  useEffect(() => { history.replaceState(null, '', `#${tab}`) }, [tab])

  const control = (action: string, value?: number) => post('/api/sim/control', { action, value })
  const step = data?.step ?? 0

  return (
    <div className="min-h-full">
      <header className="sticky top-0 z-10" style={{ background: 'var(--bg)', borderBottom: '1px solid var(--line)' }}>
        <div className="mx-auto max-w-[1500px] px-4 py-3 flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-baseline gap-3 min-w-0">
            <span className="font-display text-3xl font-semibold tracking-wide">AURORA</span>
            {data?.station && (
              <span className="truncate" style={{ color: 'var(--ink-2)' }}>
                {data.station.name} · <span className="num">{Math.abs(data.station.lat).toFixed(2)}°{data.station.lat < 0 ? 'S' : 'N'} {data.station.lon.toFixed(2)}°E</span>
              </span>
            )}
          </div>
          {data?.ready && (
            <div className="flex flex-wrap items-center gap-3">
              <span className="num text-lg">{new Date(data.time.replace(' ', 'T')).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })}</span>
              <StatusChip status={data.mode} />
              {!connected && <StatusChip status="warning" label="Reconnecting" />}
            </div>
          )}
          <div className="ml-auto flex flex-wrap items-center gap-2">
            {data?.ready && (
              <>
                <button className="btn" onClick={() => control(data.running ? 'pause' : 'play')} aria-label={data.running ? 'Pause simulation' : 'Run simulation'}>
                  {data.running ? 'Pause' : 'Run'}
                </button>
                <select id="speed" aria-label="Simulation speed" value={data.speed} onChange={(e) => control('speed', Number(e.target.value))}>
                  {[1, 2, 4, 8].map((s) => <option key={s} value={s}>{s * 15} min / s</option>)}
                </select>
              </>
            )}
            <button className="btn" onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}>{theme === 'dark' ? 'Light' : 'Dark'}</button>
          </div>
        </div>
        <nav className="mx-auto max-w-[1500px] px-4 flex gap-1 overflow-x-auto" aria-label="Screens">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)} aria-current={tab === t.key ? 'page' : undefined}
              className="font-display text-lg font-semibold px-4 whitespace-nowrap"
              style={{ minHeight: 48, color: tab === t.key ? 'var(--ink)' : 'var(--muted)', borderBottom: `3px solid ${tab === t.key ? 'var(--ink)' : 'transparent'}` }}>
              {t.label}
            </button>
          ))}
        </nav>
      </header>
      <main className="mx-auto max-w-[1500px] px-4 py-4">
        {!data?.ready ? <Empty>Starting the station twin and forecasters…</Empty> : (
          <>
            {tab === 'overview' && <Overview d={data} go={setTab} />}
            {tab === 'forecast' && <Forecast step={step} />}
            {tab === 'decisions' && <Decisions step={step} />}
            {tab === 'fuel' && <Fuel />}
            {tab === 'lab' && <Lab onInjected={setTab} />}
          </>
        )}
        <footer className="mt-8 mb-4 text-xs flex flex-wrap gap-x-4" style={{ color: 'var(--muted)' }}>
          <span>AURORA prototype · SIH PS 26061 · NCPOR, MoES</span>
          <span>Digital twin with NASA POWER weather and synthetic loads. All figures simulated.</span>
          {data?.ready && <span className="num">Fuel burned this run: {fmt.l(data.live_savings.aurora_fuel_l)}</span>}
        </footer>
      </main>
    </div>
  )
}
