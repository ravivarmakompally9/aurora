import { useEffect, useRef, useState } from 'react'

export type Card = {
  time: string; local: string; step: number; level: 'info' | 'advisory' | 'warning' | 'critical'
  kind: string; title: string; reason: string; fuel_impact_l: number | null
}

export type Overview = {
  ready: boolean
  station: { key: string; name: string; location: string; lat: number; lon: number
    gensets: { id: string; rated_kw: number }[]; pv_kwp: number; wind_kw: number; battery_kwh: number; tank_kwh: number
    storm_targets?: { soc: number; tank: number } }
  time: string; step: number; running: boolean; speed: number; mode: 'normal' | 'storm' | 'fallback'
  sources: { pv_kw: number; wind_kw: number; pv_avail_kw: number; wind_avail_kw: number; curtail_kw: number
    gen_kw: number; batt_kw: number; turbines_on: boolean }
  gens: { id: string; kw: number; on: boolean; loading_pct: number; available: boolean }[]
  loads: { el_kw: number; water_kw: number; laundry_kw: number; p2h_kw: number; tiers: Record<string, number>; unserved_kw: number }
  heat: { demand_kw: number; recovered_kw: number; p2h_kw: number; boiler_kw: number; tank_ch_kw: number; tank_dis_kw: number; dump_kw: number }
  storage: { soc: number; tank_soc: number }
  weather: { temp_c: number; wind_ms: number; hub_wind_ms: number; ghi_wm2: number; sun_up: boolean }
  fuel: { level_l: number; reserve_l: number; capacity_l: number; survival_score: number | null
    survival_score_diesel_first: number | null; level: string | null; resupply: string; delay_days: number }
  renewable_share_24h: number
  live_savings: { aurora_fuel_l: number; diesel_first_fuel_l: number; saved_l: number; saved_pct: number; co2_avoided_kg: number; hours: number }
  storm: { active: boolean; hours_to_onset: number | null; prob_max: number; peak_wind_ms: number; message: string } | null
  plan_summary: { plan_fuel_l?: number; diesel_first_fuel_l?: number; saving_l?: number; drivers?: string[]; solve_s?: number; gen_unit_hours?: number }
  sensors: Record<string, string>
  alerts: Card[]
  events: { time: string; type: string; message?: string; metric?: string; flag?: string }[]
}

export async function get<T>(path: string): Promise<T> {
  const r = await fetch(path)
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

export type Toast = { id: number; text: string; status: 'ok' | 'info' | 'critical' | 'busy'; sticky?: boolean }
let toastSeq = 0
/** Show a message in the corner (the App renders them). Sticky messages stay until dismissed. */
export function notify(text: string, status: Toast['status'] = 'ok', sticky = false): number {
  const id = ++toastSeq
  window.dispatchEvent(new CustomEvent<Toast>('aurora-toast', { detail: { id, text, status, sticky } }))
  return id
}
export function dismiss(id: number) {
  window.dispatchEvent(new CustomEvent<number>('aurora-toast-dismiss', { detail: id }))
}
/** Run a slow server action with a visible "working…" message until it finishes. */
export async function withProgress<T>(text: string, fn: () => Promise<T>): Promise<T> {
  const id = notify(text, 'busy', true)
  try { return await fn() } finally { dismiss(id) }
}

/** POST with a timeout and a readable error, so a click never fails silently. */
export async function post<T>(path: string, body: unknown, timeoutMs = 180000): Promise<T> {
  const ctl = new AbortController()
  const timer = window.setTimeout(() => ctl.abort(), timeoutMs)
  try {
    const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body), signal: ctl.signal })
    if (!r.ok) {
      const detail = await r.text().then((t) => { try { return JSON.parse(t).detail ?? t } catch { return t } })
      throw new Error(r.status === 404 || r.status === 405
        ? 'The server is running an older version of AURORA. Restart it (uv run aurora serve) and reload this page.'
        : `Server error ${r.status}: ${detail}`)
    }
    return r.json()
  } catch (e) {
    const msg = (e as Error).name === 'AbortError' ? 'The station server took too long to answer. It may be busy; try again in a moment.'
      : (e as Error).message.startsWith('Failed to fetch') ? 'Cannot reach the AURORA server. Is it running?' : (e as Error).message
    notify(msg, 'critical')
    throw new Error(msg)
  } finally {
    clearTimeout(timer)
  }
}

/** Live station overview over WebSocket, with polling as a fallback. */
export function useLive(): { data: Overview | null; connected: boolean } {
  const [data, setData] = useState<Overview | null>(null)
  const [connected, setConnected] = useState(false)
  const retry = useRef<number | undefined>(undefined)
  // after a reset (e.g. a demo preset) the server is briefly "not ready": keep showing the last good state
  const keep = (d: Overview) => setData((prev) => (d.ready || !prev?.ready ? d : prev))
  useEffect(() => {
    let ws: WebSocket | null = null
    let stopped = false
    let poll: number | undefined
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/live`)
      ws.onopen = () => { setConnected(true); if (poll) { clearInterval(poll); poll = undefined } }
      ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'overview') keep(m.data) }
      ws.onclose = () => {
        setConnected(false)
        if (!poll) poll = window.setInterval(() => get<Overview>('/api/state').then(keep).catch(() => {}), 2000)
        if (!stopped) retry.current = window.setTimeout(connect, 3000)
      }
    }
    connect()
    get<Overview>('/api/state').then((d) => { if (!stopped) setData((cur) => cur ?? d) }).catch(() => {}) // first paint without waiting for the socket
    return () => { stopped = true; ws?.close(); clearTimeout(retry.current); if (poll) clearInterval(poll) }
  }, [])
  return { data, connected }
}

const lastData = new Map<string, unknown>() // last answer per endpoint: revisiting a page shows it at once

/** Poll an endpoint every `ms` (refetches when `key` changes). */
export function usePoll<T>(path: string, ms: number, key?: unknown): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(() => (lastData.get(path) as T) ?? null)
  const [error, setError] = useState<string | null>(null)
  const [n, setN] = useState(0)
  useEffect(() => {
    let alive = true
    const load = () => get<T>(path).then((d) => { lastData.set(path, d); if (alive) { setData(d); setError(null) } }).catch((e) => alive && setError(String(e)))
    load()
    const id = window.setInterval(load, ms)
    return () => { alive = false; clearInterval(id) }
  }, [path, ms, key, n])
  return { data, error, reload: () => setN((x) => x + 1) }
}

export const fmt = {
  kw: (v: number) => `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} kW`,
  l: (v: number) => `${Math.round(v).toLocaleString('en-IN')} L`,
  kl: (v: number) => `${(v / 1000).toFixed(1)} kL`,
  pct: (v: number, d = 0) => `${(100 * v).toFixed(d)}%`,
  time: (s: string) => {
    const d = new Date(s.replace(' ', 'T'))
    return d.toLocaleString('en-GB', { weekday: 'short', hour: '2-digit', minute: '2-digit' })
  },
  date: (s: string) => new Date(s.replace(' ', 'T')).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }),
}
