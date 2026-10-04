import type { Card } from '../api'
import { fmt, usePoll } from '../api'
import { Empty, Panel, StatusChip } from '../ui'

type D = {
  cards: Card[]; mode: string
  summary: { plan_fuel_l?: number; diesel_first_fuel_l?: number; saving_l?: number; gen_unit_hours?: number; renewable_share_pct?: number; drivers?: string[]; solve_s?: number }
  solver: { last_s: number | null; mean_s: number | null; failures: number }
}

const KIND_LABEL: Record<string, string> = {
  action: 'Dispatch', storm: 'Storm Mode', guardrail: 'Safety guardrail', fallback: 'Fallback', schedule: 'Scheduling',
}

/** Screen 3: every action with a plain-language reason and its fuel impact (FR-26). */
export default function Decisions({ step }: { step: number }) {
  const { data } = usePoll<D>('/api/decisions', 3000, step)
  if (!data) return <Empty>Loading decisions…</Empty>
  const s = data.summary
  return (
    <div className="grid gap-4 grid-cols-1 xl:grid-cols-[360px_minmax(0,1fr)]">
      <div className="grid gap-4 content-start">
        <Panel title="Current 48 h plan">
          {s.plan_fuel_l !== undefined ? (
            <dl className="grid grid-cols-2 gap-y-3 gap-x-4">
              <dt className="label self-center">AURORA plan</dt><dd className="num text-xl">{fmt.l(s.plan_fuel_l)}</dd>
              <dt className="label self-center">Diesel-first rules</dt><dd className="num text-xl">{fmt.l(s.diesel_first_fuel_l ?? 0)}</dd>
              <dt className="label self-center">Difference</dt><dd className="num text-xl">{fmt.l(s.saving_l ?? 0)}</dd>
              <dt className="label self-center">Generator unit-hours</dt><dd className="num text-xl">{(s.gen_unit_hours ?? 0).toFixed(1)} h</dd>
              <dt className="label self-center">Solve time</dt><dd className="num text-xl">{(s.solve_s ?? 0).toFixed(2)} s</dd>
            </dl>
          ) : <Empty>Planning…</Empty>}
          <p className="text-xs mt-3" style={{ color: 'var(--muted)' }}>Diesel-first figure is the same forecast run through today's rules. Estimates, simulated.</p>
        </Panel>
        {(s.drivers ?? []).length > 0 && (
          <Panel title="Why demand looks like this" sub="Forecast drivers vs a typical day (feature ablation)">
            <ul className="grid gap-2">{s.drivers!.map((x) => <li key={x}>Load {x}</li>)}</ul>
          </Panel>
        )}
        <Panel title="Optimiser health">
          <dl className="grid grid-cols-2 gap-y-2">
            <dt className="label">Mode</dt><dd><StatusChip status={data.mode} /></dd>
            <dt className="label">Mean solve</dt><dd className="num">{data.solver.mean_s?.toFixed(2) ?? '–'} s</dd>
            <dt className="label">Failures</dt><dd className="num">{data.solver.failures}</dd>
          </dl>
        </Panel>
      </div>

      <Panel title="Decision timeline" sub="Newest first. Fuel impacts are first-order estimates from the generator fuel curve.">
        {data.cards.length === 0 ? <Empty>No actions yet.</Empty> : (
          <ol className="grid gap-2">
            {data.cards.map((c, i) => (
              <li key={`${c.step}-${i}`} className="rounded-lg p-3 grid gap-1"
                style={{ background: 'var(--surface-2)', borderLeft: `4px solid ${c.level === 'critical' ? 'var(--critical)' : c.level === 'warning' ? 'var(--warning)' : 'var(--line)'}` }}>
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <span className="num text-sm" style={{ color: 'var(--ink-2)' }}>{c.local}</span>
                  <span className="font-display text-lg font-semibold">{c.title}</span>
                  <span className="label">{KIND_LABEL[c.kind] ?? c.kind}</span>
                  {c.fuel_impact_l !== null && c.fuel_impact_l > 0 && (
                    <span className="ml-auto num text-sm rounded-full px-2 py-0.5" style={{ border: '1px solid var(--good)' }}>
                      saves about {c.fuel_impact_l.toFixed(0)} L
                    </span>
                  )}
                </div>
                <p className="text-sm" style={{ color: 'var(--ink-2)' }}>{c.reason}</p>
              </li>
            ))}
          </ol>
        )}
      </Panel>
    </div>
  )
}
