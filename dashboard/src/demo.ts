import type { Overview } from './api'

/** Static demo build (GitHub Pages): the dashboard replays recorded runs of the digital twin
 *  instead of talking to the Python server. Built with VITE_STATIC=1. */
export const STATIC = import.meta.env.VITE_STATIC === '1'
/** Where the demo sends people for the live app: the Render deployment when VITE_LIVE_URL is set at build
 *  time (Vercel or GitHub Pages), otherwise GitHub Codespaces. */
export const LIVE_APP_URL = import.meta.env.VITE_LIVE_URL || 'https://codespaces.new/ravivarmakompally9/aurora'

type Scenario = {
  frames: Overview[]
  forecast: Record<string, unknown>
  decisions: Record<string, unknown>
  fuel: unknown
}

const SCENARIO_TAB: Record<string, string> = { normal: 'overview', blizzard: 'forecast', ship_delay: 'fuel' }
const PRESET_SCENARIO: Record<string, string> = { reset: 'normal', blizzard: 'blizzard', ship_delay: 'ship_delay' }
const INJECT_SCENARIO: Record<string, string> = { blizzard: 'blizzard', resupply_delay: 'ship_delay' }
const TITLES: Record<string, string> = {
  normal: 'Clean station: a normal day, recorded from the digital twin',
  blizzard: 'Blizzard rising in 16 h: watch Storm Mode prepare (recorded run)',
  ship_delay: 'Supply ship delayed by 30 days (recorded run)',
}

class Player {
  private data: Record<string, Scenario> = {}
  private year: unknown = null
  private listeners = new Set<() => void>()
  private timer: number | undefined
  scenario = 'normal'
  i = 0
  running = true
  speed = 1

  private async load(name: string) {
    if (!this.data[name]) {
      const r = await fetch(`demo/${name}.json`)
      if (!r.ok) throw new Error(`Recorded demo data "${name}" is missing from this build.`)
      this.data[name] = await r.json()
    }
    return this.data[name]
  }

  async start() {
    await this.load('normal')
    this.emit()
    if (this.timer === undefined) {
      this.timer = window.setInterval(() => {
        const n = this.data[this.scenario]?.frames.length ?? 0
        if (!this.running || !n) return
        this.i = Math.min(n - 1, this.i + this.speed)
        if (this.i >= n - 1) this.running = false // end of the recording: hold the last frame
        this.emit()
      }, 1000)
    }
  }

  subscribe(fn: () => void) { this.listeners.add(fn); return () => { this.listeners.delete(fn) } }
  private emit() { this.listeners.forEach((f) => f()) }

  frame(): Overview | null {
    const f = this.data[this.scenario]?.frames[this.i]
    return f ? { ...f, running: this.running, speed: this.speed } : null
  }

  private nearest(map: Record<string, unknown>) {
    const keys = Object.keys(map).map(Number).filter((k) => k <= this.i)
    return map[String(keys.length ? Math.max(...keys) : 0)]
  }

  async get(path: string): Promise<unknown> {
    const p = path.split('?')[0]
    const s = await this.load(this.scenario)
    if (p === '/api/state') return this.frame()
    if (p === '/api/forecast') return this.nearest(s.forecast)
    if (p === '/api/decisions') return this.nearest(s.decisions)
    if (p === '/api/fuel') return s.fuel
    if (p === '/api/year') {
      if (!this.year) {
        const r = await fetch('demo/year.json')
        if (!r.ok) throw new Error('404 year data not in this build')
        this.year = await r.json()
      }
      return this.year
    }
    throw new Error(`404 ${p} is not part of the recorded demo`)
  }

  private async switchTo(name: string) {
    await this.load(name)
    this.scenario = name
    this.i = 0
    this.running = true
    this.emit()
  }

  async post(path: string, body: Record<string, unknown>): Promise<unknown> {
    if (path === '/api/sim/control') {
      const a = body.action as string
      if (a === 'play') { if (this.i >= (this.data[this.scenario]?.frames.length ?? 1) - 1) this.i = 0; this.running = true }
      else if (a === 'pause') this.running = false
      else if (a === 'speed') this.speed = Math.max(1, Math.min(8, Number(body.value) || 1))
      else if (a === 'reset') await this.switchTo('normal')
      this.emit()
      return { running: this.running, speed: this.speed }
    }
    if (path === '/api/sim/preset') {
      const name = PRESET_SCENARIO[body.name as string]
      if (!name) throw new Error(`Unknown demo "${String(body.name)}"`)
      await this.switchTo(name)
      return { preset: body.name, description: TITLES[name], tab: SCENARIO_TAB[name] }
    }
    if (path === '/api/sim/inject') {
      const name = INJECT_SCENARIO[body.type as string]
      if (!name) throw new LiveOnly('This event runs the optimiser live, so it needs the full app.')
      await this.switchTo(name)
      return { message: TITLES[name] }
    }
    throw new LiveOnly('Re-scoring runs 1,000 new simulations, so it needs the full app.')
  }
}

/** An action the recorded demo cannot perform; the message points to the live app. */
export class LiveOnly extends Error {}

export const demo = new Player()
