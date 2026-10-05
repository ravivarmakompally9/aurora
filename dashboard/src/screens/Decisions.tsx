import { useMemo, useState } from 'react'
import type { Card } from '../api'
import { fmt, usePoll } from '../api'
import { Icon, IconBadge } from '../icons'
import { Bar, Empty, PageHeader, Panel, StatusChip, Verdict } from '../ui'

type D = {
  cards: Card[]; mode: string
  summary: { plan_fuel_l?: number; diesel_first_fuel_l?: number; saving_l?: number; gen_unit_hours?: number; renewable_share_pct?: number; drivers?: string[]; solve_s?: number }
  solver: { last_s: number | null; mean_s: number | null; failures: number }
}

const KINDS: Record<string, { label: string; icon: string; color: string }> = {
  action: { label: 'Dispatch', icon: 'bolt', color: 'var(--accent)' },
  storm: { label: 'Storm Mode', icon: 'blizzard', color: 'var(--warning)' },
  guardrail: { label: 'Safety guardrail', icon: 'shield', color: 'var(--good)' },
  fallback: { label: 'Fallback', icon: 'alert', color: 'var(--critical)' },
  schedule: { label: 'Scheduling', icon: 'calendar', color: 'var(--s-boiler)' },
}

/** Pick the icon that best says what a card is about. */
function cardIcon(c: Card): { icon: string; color: string } {
  const t = c.title.toLowerCase()
  if (t.includes('trip')) return { icon: 'alert', color: 'var(--critical)' }
  if (c.kind === 'storm') return { icon: 'blizzard', color: 'var(--warning)' }
  if (c.kind === 'guardrail') return { icon: 'shield', color: c.level === 'critical' ? 'var(--critical)' : 'var(--good)' }
  if (c.kind === 'fallback') return { icon: 'alert', color: 'var(--critical)' }
  if (t.includes('water')) return { icon: 'water', color: 'var(--s-battery)' }
  if (t.includes('turbine') || /\bwind\b/.test(t)) return { icon: 'wind', color: 'var(--s-wind)' }
  if (t.includes('battery')) return { icon: 'battery', color: 'var(--s-battery)' }
  if (t.includes('heat') || t.includes('tank') || t.includes('boiler')) return { icon: 'tank', color: 'var(--s-heat)' }
  if (t.includes('water')) return { icon: 'water', color: 'var(--s-battery)' }
  if (t.includes('laundry') || t.includes('shed') || t.includes('tier')) return { icon: 'comfort', color: 'var(--t4)' }
  if (t.includes('start') || t.includes('stop') || /\bg\d/.test(t) || t.includes('generator')) return { icon: 'generator', color: 'var(--s-diesel)' }
  return { icon: KINDS[c.kind]?.icon ?? 'spark', color: KINDS[c.kind]?.color ?? 'var(--accent)' }
}

/** Screen 3: every action with a plain-language reason and its fuel impact (FR-26). */
export default function Decisions({ step, go }: { step: number; go: (t: string) => void }) {
  const { data } = usePoll<D>('/api/decisions', 3000, step)
  const [kind, setKind] = useState<string>('all')
  const counts = useMemo(() => {
    const m: Record<string, number> = {}
    data?.cards.forEach((c) => { m[c.kind] = (m[c.kind] ?? 0) + 1 })
    return m
  }, [data])
  if (!data) return <div className="card"><Empty>Loading decisions…</Empty></div>
  const s = data.summary
  const cards = kind === 'all' ? data.cards : data.cards.filter((c) => c.kind === kind)
  const base = s.diesel_first_fuel_l ?? 0, plan = s.plan_fuel_l ?? 0
  const saved = base > 0 ? (base - plan) / base : 0
  const totalSaved = data.cards.reduce((a, c) => a + (c.fuel_impact_l && c.fuel_impact_l > 0 ? c.fuel_impact_l : 0), 0)

  return (
    <>
      <PageHeader step="Step 3 of 5 · Why AURORA acted" title="Why did AURORA do that?"
        question="Every action comes with a reason in plain words and an estimate of the diesel it saves. The safety guardrail's corrections are listed too."
        actions={<button className="btn" onClick={() => go('fuel')}>Next: will fuel last?<Icon name="arrow" size={16} /></button>}>
        {s.plan_fuel_l !== undefined && (
          <Verdict status="ok">This 48-hour plan uses <b className="num">{fmt.l(plan)}</b> of diesel, <b className="num">{(saved * 100).toFixed(0)}% less</b> than today's rules would on the same forecast.</Verdict>
        )}
      </PageHeader>

      <div className="grid gap-5 grid-cols-1 xl:grid-cols-[380px_minmax(0,1fr)]">
        <div className="grid gap-5 content-start">
          <Panel title="This 48 h plan vs today's rules" icon={<IconBadge name="spark" color="var(--accent)" />}>
            {s.plan_fuel_l !== undefined ? (
              <>
                <div className="label">Diesel saved on this forecast</div>
                <div className="big text-[2.2rem] mt-1" style={{ color: 'var(--accent)' }}>{Math.round(s.saving_l ?? 0).toLocaleString('en-IN')}<span className="unit">L</span>
                  <span className="text-base font-semibold ml-2" style={{ color: 'var(--ink-2)' }}>({(saved * 100).toFixed(0)}% less)</span></div>
                <div className="grid gap-2.5 mt-4">
                  {[{ label: "Today's rules", v: base, c: 'var(--s-base)' }, { label: 'AURORA plan', v: plan, c: 'var(--accent)' }].map((x) => (
                    <div key={x.label}>
                      <div className="flex justify-between text-sm"><span style={{ color: 'var(--ink-2)' }}>{x.label}</span><span className="num">{fmt.l(x.v)}</span></div>
                      <Bar value={x.v} max={Math.max(base, plan, 1)} color={x.c} height={12} />
                    </div>
                  ))}
                </div>
                <div className="grid grid-cols-2 gap-2.5 mt-4">
                  <div className="tile p-3"><div className="label">Engine hours</div><div className="big text-lg mt-1">{(s.gen_unit_hours ?? 0).toFixed(1)} h</div></div>
                  <div className="tile p-3"><div className="label">Solve time</div><div className="big text-lg mt-1">{(s.solve_s ?? 0).toFixed(2)} s</div></div>
                </div>
              </>
            ) : <Empty>Planning…</Empty>}
            <p className="text-xs mt-3 mb-0" style={{ color: 'var(--muted)' }}>The comparison runs the same forecast through today's diesel-first rules. Estimates, simulated.</p>
          </Panel>

          {(s.drivers ?? []).length > 0 && (
            <Panel title="Why demand looks like this" sub="Forecast drivers against a typical day">
              <ul className="grid gap-2 m-0 p-0 list-none">
                {s.drivers!.map((x) => <li key={x} className="flex gap-2.5 items-start"><Icon name="forecast" size={18} color="var(--accent)" />Load {x}</li>)}
              </ul>
            </Panel>
          )}

          <Panel title="Optimiser health" icon={<IconBadge name="cpu" color={data.mode === 'fallback' ? 'var(--critical)' : 'var(--good)'} />}>
            <div className="grid grid-cols-3 gap-2.5">
              <div className="tile p-3 grid gap-1"><div className="label">Mode</div><StatusChip status={data.mode} /></div>
              <div className="tile p-3"><div className="label">Mean solve</div><div className="big text-lg mt-1">{data.solver.mean_s?.toFixed(2) ?? '–'} s</div></div>
              <div className="tile p-3"><div className="label">Failures</div><div className="num text-lg" style={{ color: data.solver.failures ? 'var(--warning)' : undefined }}>{data.solver.failures}</div></div>
            </div>
          </Panel>
        </div>

        <Panel title="Decision timeline" sub={`Newest first · ${data.cards.length} decision${data.cards.length === 1 ? '' : 's'}${totalSaved > 0 ? ` · about ${fmt.l(totalSaved)} saved by the ones with a fuel estimate` : ''}`}>
          <div className="flex flex-wrap gap-2 mb-4" role="group" aria-label="Filter decisions">
            {[['all', 'All', data.cards.length], ...Object.entries(KINDS).filter(([k]) => counts[k]).map(([k, v]) => [k, v.label, counts[k]])].map(([k, label, n]) => (
              <button key={String(k)} aria-pressed={kind === k} onClick={() => setKind(String(k))} className="btn !min-h-[40px] !px-3.5 !text-sm"
                style={kind === k ? { background: 'var(--ink)', color: '#fff', borderColor: 'var(--ink)' } : undefined}>
                {k !== 'all' && <Icon name={KINDS[String(k)].icon} size={16} color={KINDS[String(k)].color} />}{label}
                <span className="num text-xs" style={{ color: 'var(--muted)' }}>{n}</span>
              </button>
            ))}
          </div>
          {cards.length === 0 ? <Empty><p className="m-0 max-w-[460px]"><b style={{ color: 'var(--ink)' }}>No decisions yet.</b> Press <b style={{ color: 'var(--ink)' }}>Run</b> at the top right. As simulated time passes, every generator start, battery choice and safety correction appears here with its reason.</p></Empty> : (
            <ol className="relative grid gap-3 m-0 p-0 list-none">
              <div aria-hidden className="absolute top-2 bottom-2" style={{ left: 21, width: 2, background: 'linear-gradient(var(--line-2), transparent)' }} />
              {cards.slice(0, 80).map((c, i) => {
                const ic = cardIcon(c)
                const tone = c.level === 'critical' ? 'var(--critical)' : c.level === 'warning' ? 'var(--warning)' : null
                return (
                  <li key={`${c.step}-${i}`} className="relative grid gap-3" style={{ gridTemplateColumns: '44px 1fr' }}>
                    <span className="relative z-[1]"><IconBadge name={ic.icon} color={ic.color} size={44} /></span>
                    <div className="rounded-2xl p-3.5 grid gap-1" style={{ background: tone ? `color-mix(in srgb, ${tone} 7%, white)` : 'var(--card)',
                      border: `1px solid ${tone ? `color-mix(in srgb, ${tone} 30%, white)` : 'var(--line)'}` }}>
                      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                        <span className="text-[1rem] font-bold">{c.title}</span>
                        <span className="label">{KINDS[c.kind]?.label ?? c.kind}</span>
                        <span className="num text-xs" style={{ color: 'var(--muted)' }}>{c.local}</span>
                        {c.fuel_impact_l !== null && c.fuel_impact_l > 0 && (
                          <span className="ml-auto pill num" style={{ background: 'var(--good-soft)', color: 'var(--good)' }}>
                            <Icon name="drop" size={14} />saves ~{c.fuel_impact_l.toFixed(0)} L
                          </span>
                        )}
                      </div>
                      <p className="text-sm m-0" style={{ color: 'var(--ink-2)' }}>{c.reason}</p>
                    </div>
                  </li>
                )
              })}
            </ol>
          )}
        </Panel>
      </div>
    </>
  )
}
