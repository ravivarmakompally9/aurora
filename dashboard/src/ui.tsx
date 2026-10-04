import type { ReactNode } from 'react'

export const SERIES = {
  solar: 'var(--s-solar)', wind: 'var(--s-wind)', diesel: 'var(--s-diesel)', battery: 'var(--s-battery)',
  heat: 'var(--s-heat)', boiler: 'var(--s-boiler)', load: 'var(--s-load)', base: 'var(--s-base)',
}

const STATUS: Record<string, { color: string; icon: string; label: string }> = {
  normal: { color: 'var(--good)', icon: '●', label: 'Normal' },
  storm: { color: 'var(--warning)', icon: '▲', label: 'Storm Mode' },
  fallback: { color: 'var(--critical)', icon: '■', label: 'Fallback' },
  ok: { color: 'var(--good)', icon: '●', label: 'Safe' },
  warning: { color: 'var(--warning)', icon: '▲', label: 'Watch' },
  critical: { color: 'var(--critical)', icon: '■', label: 'At risk' },
  info: { color: 'var(--focus)', icon: 'i', label: 'Info' },
  advisory: { color: 'var(--good)', icon: '◆', label: 'Advisory' },
}

export function StatusChip({ status, label }: { status: string; label?: string }) {
  const s = STATUS[status] ?? STATUS.info
  return (
    <span className="inline-flex items-center gap-2 rounded-full px-3 py-1 text-sm font-semibold"
      style={{ border: `1px solid ${s.color}`, color: 'var(--ink)' }}>
      <span aria-hidden style={{ color: s.color }}>{s.icon}</span>{label ?? s.label}
    </span>
  )
}

export function Panel({ title, sub, right, children, className = '' }:
  { title?: string; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <section className={`panel p-4 min-w-0 ${className}`}>
      {(title || right) && (
        <header className="flex flex-wrap items-start justify-between gap-2 mb-3">
          <div className="min-w-0">
            {title && <h2 className="font-display text-xl font-semibold leading-tight">{title}</h2>}
            {sub && <p className="text-sm" style={{ color: 'var(--ink-2)' }}>{sub}</p>}
          </div>
          {right}
        </header>
      )}
      {children}
    </section>
  )
}

export function Stat({ label, value, sub, big = false }: { label: string; value: ReactNode; sub?: ReactNode; big?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="label">{label}</div>
      <div className={`num font-semibold ${big ? 'text-5xl' : 'text-2xl'} leading-tight`}>{value}</div>
      {sub && <div className="text-sm mt-0.5" style={{ color: 'var(--ink-2)' }}>{sub}</div>}
    </div>
  )
}

export function Meter({ value, max = 1, color, marker, height = 10 }:
  { value: number; max?: number; color: string; marker?: number; height?: number }) {
  const pct = Math.max(0, Math.min(1, value / max)) * 100
  return (
    <div className="relative w-full rounded-full" style={{ height, background: 'var(--surface-2)', border: '1px solid var(--line)' }}>
      <div className="h-full rounded-full" style={{ width: `${pct}%`, background: color }} />
      {marker !== undefined && (
        <div className="absolute top-[-4px]" style={{ left: `${(marker / max) * 100}%`, height: height + 8, width: 2, background: 'var(--ink)' }} />
      )}
    </div>
  )
}

export function Legend({ items }: { items: { label: string; color: string; kind?: 'line' | 'area' | 'band' | 'dash' }[] }) {
  return (
    <div className="flex flex-wrap gap-x-4 gap-y-1 text-sm" style={{ color: 'var(--ink-2)' }}>
      {items.map((i) => (
        <span key={i.label} className="inline-flex items-center gap-1.5">
          {i.kind === 'line' || i.kind === 'dash' ? (
            <svg width="18" height="8" aria-hidden><line x1="0" y1="4" x2="18" y2="4" stroke={i.color} strokeWidth="2.5"
              strokeDasharray={i.kind === 'dash' ? '4 3' : undefined} /></svg>
          ) : (
            <span className="inline-block rounded-sm" style={{ width: 12, height: 12, background: i.color, opacity: i.kind === 'band' ? 0.35 : 1 }} />
          )}
          {i.label}
        </span>
      ))}
    </div>
  )
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="py-10 text-center" style={{ color: 'var(--muted)' }}>{children}</div>
}

export const tooltipStyle = {
  contentStyle: { background: 'var(--surface)', border: '1px solid var(--line)', borderRadius: 8, color: 'var(--ink)', fontSize: 12 },
  labelStyle: { color: 'var(--ink-2)', fontFamily: 'var(--font-mono)' },
  itemStyle: { color: 'var(--ink)', fontFamily: 'var(--font-mono)', padding: 0 },
}
