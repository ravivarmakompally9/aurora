import type { CSSProperties } from 'react'
import {
  Activity, ArrowRight, BatteryCharging, Calendar, Check, CircleCheck, CircleHelp, Clock, CloudSnow, Cpu, Cylinder, Droplets,
  Factory, FlaskConical, Flame, Fuel, Gauge, HeartPulse, LayoutDashboard, Leaf, Lightbulb, ListChecks, ChartSpline, Moon, Pause,
  Play, Radio, RotateCcw, SatelliteDish, ShieldCheck, Ship, Siren, Snowflake, Sparkles, Sun, Target, Thermometer, Timer,
  TrendingDown, TriangleAlert, WashingMachine, Wind, Wrench, X, Zap, Boxes, type LucideIcon,
} from 'lucide-react'

/** One professional icon set (Lucide, ISC licence, bundled for offline use). Screens refer to icons by name. */
const MAP: Record<string, LucideIcon> = {
  overview: LayoutDashboard, forecast: ChartSpline, decisions: ListChecks, fuel: Fuel, lab: Boxes,
  solar: Sun, wind: Wind, breeze: Wind, generator: Factory, battery: BatteryCharging, tank: Cylinder, flame: Flame,
  blizzard: CloudSnow, snow: Snowflake, ship: Ship, drop: Droplets, water: Droplets, leak: Droplets, heart: HeartPulse,
  comms: SatelliteDish, science: FlaskConical, comfort: WashingMachine, shield: ShieldCheck, spark: Sparkles, leaf: Leaf,
  play: Play, pause: Pause, sun: Sun, moon: Moon, thermo: Thermometer, alert: TriangleAlert, clock: Clock, bolt: Zap,
  arrow: ArrowRight, calendar: Calendar, sensor: Radio, reset: RotateCcw, cpu: Cpu, check: Check, done: CircleCheck,
  help: CircleHelp, close: X, gauge: Gauge, activity: Activity, idea: Lightbulb, target: Target, saving: TrendingDown,
  timer: Timer, siren: Siren, wrench: Wrench,
}

export type IconName = keyof typeof MAP

export function Icon({ name, size = 20, color, className = '', style, title, strokeWidth = 2 }:
  { name: IconName | string; size?: number; color?: string; className?: string; style?: CSSProperties; title?: string; strokeWidth?: number }) {
  const C = MAP[name] ?? Sparkles
  return <C size={size} color={color} strokeWidth={strokeWidth} className={className} style={{ flex: 'none', ...style }}
    aria-hidden={title ? undefined : true} aria-label={title} role={title ? 'img' : undefined} />
}

/** Icon on a soft tinted square in the series colour. */
export function IconBadge({ name, color, size = 40 }: { name: IconName | string; color: string; size?: number }) {
  return (
    <span className="badge" style={{ width: size, height: size, color, background: `color-mix(in srgb, ${color} 12%, white)` }}>
      <Icon name={name} size={Math.round(size * 0.5)} />
    </span>
  )
}

export function Logo({ size = 36 }: { size?: number }) {
  return (
    <svg viewBox="0 0 40 40" width={size} height={size} role="img" aria-label="AURORA">
      <defs>
        <linearGradient id="logo-g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stopColor="#14B8A6" /><stop offset="1" stopColor="#2563EB" /></linearGradient>
      </defs>
      <rect x="1" y="1" width="38" height="38" rx="11" fill="url(#logo-g)" />
      <path d="M9 27c3.5-9 7-13 11-13s7.5 4 11 13" fill="none" stroke="#fff" strokeWidth="3" strokeLinecap="round" />
      <path d="M13.5 27c2-5 4.2-7.5 6.5-7.5s4.5 2.5 6.5 7.5" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" opacity=".6" />
    </svg>
  )
}
