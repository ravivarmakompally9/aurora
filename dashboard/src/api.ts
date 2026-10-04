import { useEffect, useRef, useState } from 'react'

export type Card = {
  time: string; local: string; step: number; level: 'info' | 'advisory' | 'warning' | 'critical'
  kind: string; title: string; reason: string; fuel_impact_l: number | null
}

export type Overview = {
  ready: boolean
  station: { key: string; name: string; location: string; lat: number; lon: number
    gensets: { id: string; rated_kw: number }[]; pv_kwp: number; wind_kw: number; battery_kwh: number; tank_kwh: number }
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

export async function post<T>(path: string, body: unknown): Promise<T> {
  const r = await fetch(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`)
  return r.json()
}

/** Live station overview over WebSocket, with polling as a fallback. */
export function useLive(): { data: Overview | null; connected: boolean } {
  const [data, setData] = useState<Overview | null>(null)
  const [connected, setConnected] = useState(false)
  const retry = useRef<number | undefined>(undefined)
  useEffect(() => {
    let ws: WebSocket | null = null
    let stopped = false
    let poll: number | undefined
    const connect = () => {
      const proto = location.protocol === 'https:' ? 'wss' : 'ws'
      ws = new WebSocket(`${proto}://${location.host}/ws/live`)
      ws.onopen = () => { setConnected(true); if (poll) { clearInterval(poll); poll = undefined } }
      ws.onmessage = (e) => { const m = JSON.parse(e.data); if (m.type === 'overview') setData(m.data) }
      ws.onclose = () => {
        setConnected(false)
        if (!poll) poll = window.setInterval(() => get<Overview>('/api/state').then(setData).catch(() => {}), 2000)
        if (!stopped) retry.current = window.setTimeout(connect, 3000)
      }
    }
    connect()
    return () => { stopped = true; ws?.close(); clearTimeout(retry.current); if (poll) clearInterval(poll) }
  }, [])
  return { data, connected }
}

/** Poll an endpoint every `ms` (refetches when `key` changes). */
export function usePoll<T>(path: string, ms: number, key?: unknown): { data: T | null; error: string | null; reload: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [n, setN] = useState(0)
  useEffect(() => {
    let alive = true
    const load = () => get<T>(path).then((d) => { if (alive) { setData(d); setError(null) } }).catch((e) => alive && setError(String(e)))
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
