import type { CSSProperties, ReactNode } from 'react'
import { Icon } from './icons'

export const SERIES = {
  solar: 'var(--s-solar)', wind: 'var(--s-wind)', diesel: 'var(--s-diesel)', battery: 'var(--s-battery)',
  heat: 'var(--s-heat)', boiler: 'var(--s-boiler)', load: 'var(--s-load)', base: 'var(--s-base)', accent: 'var(--accent)',
}

const STATUS: Record<string, { color: string; soft: string; icon: string; label: string }> = {
  normal: { color: 'var(--good)', soft: 'var(--good-soft)', icon: 'shield', label: 'Normal operation' },
  storm: { color: 'var(--warning)', soft: 'var(--warning-soft)', icon: 'blizzard', label: 'Storm Mode' },
  fallback: { color: 'var(--critical)', soft: 'var(--critical-soft)', icon: 'alert', label: 'Fallback rules' },
  ok: { color: 'var(--good)', soft: 'var(--good-soft)', icon: 'done', label: 'Safe' },
  warning: { color: 'var(--warning)', soft: 'var(--warning-soft)', icon: 'alert', label: 'Watch' },
  critical: { color: 'var(--critical)', soft: 'var(--critical-soft)', icon: 'siren', label: 'At risk' },
  info: { color: 'var(--focus)', soft: '#eaf1fe', icon: 'spark', label: 'Info' },
  advisory: { color: 'var(--good)', soft: 'var(--good-soft)', icon: 'idea', label: 'Advisory' },
}
export const statusOf = (s: string) => STATUS[s] ?? STATUS.info

export function StatusChip({ status, label, dot = false }: { status: string; label?: string; dot?: boolean }) {
  const s = statusOf(status)
  return (
    <span className="pill" style={{ background: s.soft, color: s.color }}>
      {dot ? <span className="pulse" style={{ width: 7, height: 7, borderRadius: 9, background: s.color }} /> : <Icon name={s.icon} size={15} />}
      {label ?? s.label}
    </span>
  )
}

/** Every screen opens with: what this page answers, the answer right now, and what to do next. */
export function PageHeader({ step, title, question, children, actions }:
  { step?: string; title: string; question: string; children?: ReactNode; actions?: ReactNode }) {
  return (
    <header className="flex flex-wrap items-end justify-between gap-4 px-1 rise">
      <div className="min-w-0 max-w-[820px]">
        {step && <div className="eyebrow">{step}</div>}
        <h1 className="text-[1.75rem] sm:text-[2rem] font-bold tracking-tight m-0 mt-1 leading-tight">{title}</h1>
        <p className="m-0 mt-1 text-[0.975rem]" style={{ color: 'var(--ink-2)' }}>{question}</p>
        {children}
      </div>
      {actions && <div className="flex flex-wrap gap-2.5">{actions}</div>}
    </header>
  )
}

/** One-sentence answer, coloured by how good the news is. */
export function Verdict({ status, children }: { status: string; children: ReactNode }) {
  const s = statusOf(status)
  return (
    <div className="mt-3 inline-flex items-start gap-2.5 rounded-xl px-3.5 py-2.5 text-[0.95rem] font-medium" style={{ background: s.soft, color: 'var(--ink)' }}>
      <span style={{ color: s.color, marginTop: 2 }}><Icon name={s.icon} size={18} /></span><span>{children}</span>
    </div>
  )
}

export function Panel({ title, sub, right, icon, children, className = '', style, help }:
  { title?: ReactNode; sub?: ReactNode; right?: ReactNode; icon?: ReactNode; children: ReactNode; className?: string; style?: CSSProperties; help?: string }) {
  return (
    <section className={`card p-5 sm:p-6 min-w-0 rise ${className}`} style={style}>
      {(title || right) && (
        <header className="flex flex-wrap items-start justify-between gap-3 mb-4">
          <div className="flex items-start gap-3 min-w-0">
            {icon}
            <div className="min-w-0">
              {title && (
                <h2 className="text-[1.125rem] font-bold leading-tight m-0 flex items-center gap-1.5">
                  {title}
                  {help && <span title={help} style={{ color: 'var(--muted)', cursor: 'help' }}><Icon name="help" size={16} /></span>}
                </h2>
              )}
              {sub && <p className="sub m-0 mt-1">{sub}</p>}
            </div>
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  )
}

/** Big number with a small grey unit, a label above and a short explanation below. */
export function Kpi({ label, value, unit, note, icon, color, tone }:
  { label: string; value: ReactNode; unit?: string; note?: ReactNode; icon?: string; color?: string; tone?: string }) {
  return (
    <div className="card p-5 min-w-0 rise">
      <div className="flex items-center justify-between gap-2">
        <span className="label">{label}</span>
        {icon && <span style={{ color: color ?? 'var(--muted)' }}><Icon name={icon} size={18} /></span>}
      </div>
      <div className="big text-[2.1rem] mt-2" style={{ color: tone }}>{value}{unit && <span className="unit">{unit}</span>}</div>
      {note && <div className="text-[0.8125rem] mt-1.5" style={{ color: 'var(--ink-2)' }}>{note}</div>}
    </div>
  )
}

export function Bar({ value, max = 1, color, height = 8, marker, markerLabel, track = 'var(--tile-2)' }:
  { value: number; max?: number; color: string; height?: number; marker?: number; markerLabel?: string; track?: string }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100
  return (
    <div className="relative w-full" style={{ height, borderRadius: height, background: track }}>
      <div style={{ width: `${pct}%`, height: '100%', borderRadius: height, background: color, transition: 'width .6s ease' }} />
      {marker !== undefined && (
        <div className="absolute" title={markerLabel} style={{ left: `${(marker / max) * 100}%`, top: -4, bottom: -4, width: 2, borderRadius: 2, background: 'var(--ink)' }} />
      )}
    </div>
  )
}

/** 100% split bar with labels underneath: easier to read than a pie. */
export function SplitBar({ parts, height = 14 }: { parts: { label: string; value: number; color: string; icon?: string }[]; height?: number }) {
  const total = Math.max(1e-9, parts.reduce((a, p) => a + Math.max(0, p.value), 0))
  return (
    <div>
      <div className="flex gap-[3px] overflow-hidden" style={{ height, borderRadius: height }}>
        {parts.filter((p) => p.value > 0).map((p) => (
          <div key={p.label} title={`${p.label}: ${Math.round((100 * p.value) / total)}%`} style={{ flex: p.value, background: p.color, minWidth: 4, transition: 'flex .6s ease' }} />
        ))}
      </div>
      <div className="flex flex-wrap gap-x-5 gap-y-1.5 mt-2.5">
        {parts.map((p) => (
          <span key={p.label} className="inline-flex items-center gap-1.5 text-[0.8125rem]" style={{ color: 'var(--ink-2)' }}>
            {p.icon ? <span style={{ color: p.color }}><Icon name={p.icon} size={15} /></span> : <span style={{ width: 9, height: 9, borderRadius: 3, background: p.color }} />}
            {p.label} <b className="num" style={{ color: 'var(--ink)' }}>{Math.round((100 * p.value) / total)}%</b>
          </span>
        ))}
      </div>
    </div>
  )
}

/** 100 dots, one per simulated future: "fuel lasts in 98 of 100 futures". Risk communicated as counts. */
export function FutureDots({ share, color = 'var(--good)', miss = 'var(--critical)', size = 11, gap = 4 }:
  { share: number; color?: string; miss?: string; size?: number; gap?: number }) {
  const ok = Math.round(Math.max(0, Math.min(1, share)) * 100)
  return (
    <div className="grid w-full" style={{ gridTemplateColumns: 'repeat(20, minmax(0, 1fr))', gap: `min(${gap}px, 0.6vw)`, maxWidth: 20 * (size + gap) }}
      role="img" aria-label={`${ok} of 100 simulated futures`}>
      {Array.from({ length: 100 }, (_, i) => (
        <span key={i} style={{ aspectRatio: '1', borderRadius: '50%', background: i < ok ? color : `color-mix(in srgb, ${miss} 70%, white)` }} />
      ))}
    </div>
  )
}

export function Swatch({ color, kind = 'box' }: { color: string; kind?: 'box' | 'line' | 'dash' | 'band' }) {
  if (kind === 'line' || kind === 'dash') {
    return <svg width="18" height="8" aria-hidden><line x1="1" y1="4" x2="17" y2="4" stroke={color} strokeWidth="2.5" strokeLinecap="round" strokeDasharray={kind === 'dash' ? '3 4' : undefined} /></svg>
  }
  return <span className="inline-block" style={{ width: 10, height: 10, borderRadius: 3, background: color, opacity: kind === 'band' ? 0.35 : 1 }} />
}

export function Legend({ items }: { items: { label: string; color: string; kind?: 'box' | 'line' | 'dash' | 'band'; icon?: string }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1.5 text-[0.8125rem]" style={{ color: 'var(--ink-2)' }}>
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          {i.icon ? <span style={{ color: i.color }}><Icon name={i.icon} size={15} /></span> : <Swatch color={i.color} kind={i.kind} />}
          {i.label}
        </span>
      ))}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return (
    <div className="py-12 grid place-items-center gap-3 text-center" style={{ color: 'var(--muted)' }}>
      <span className="pulse" style={{ color: 'var(--accent)' }}><Icon name="activity" size={26} /></span>
      {children}
    </div>
  )
}

export function Callout({ children, status = 'info' }: { children: ReactNode; status?: string }) {
  const s = statusOf(status)
  return (
    <div className="rounded-xl px-4 py-3 text-sm flex gap-2.5 items-start" style={{ background: s.soft }}>
      <span style={{ color: s.color, marginTop: 1 }}><Icon name={s.icon} size={17} /></span><div className="min-w-0">{children}</div>
    </div>
  )
}

export const tooltipStyle = {
  contentStyle: { background: '#fff', border: '1px solid var(--line-2)', borderRadius: 12, color: 'var(--ink)', fontSize: 12,
    boxShadow: '0 12px 32px -12px rgba(15,23,42,.25)', fontFamily: 'var(--font)' },
  labelStyle: { color: 'var(--muted)', fontWeight: 600, marginBottom: 4 },
  itemStyle: { color: 'var(--ink)', padding: 0, fontWeight: 600 },
  cursor: { stroke: 'var(--line-2)', strokeWidth: 1 },
}
