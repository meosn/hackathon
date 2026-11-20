import { BookOpenCheck, Layers3, Copy, ShieldAlert, Timer } from 'lucide-react'
import { label, useApi } from '../../api/client'
import type { Costs } from '../../api/types'
import { Badge, Card, ErrorNote, Loading } from '../../components/UI'
const count = (n: number) => Intl.NumberFormat().format(n)
const dollars = (n: number | null) =>
  n === null
    ? 'Unavailable'
    : new Intl.NumberFormat('en-US', {
        style: 'currency',
        currency: 'USD',
        minimumFractionDigits: 2,
        maximumFractionDigits: 6,
      }).format(n)
export function Analytics() {
  const q = useApi<Costs>('/metrics/costs')
  if (q.isPending) return <Loading />
  if (!q.data) return <ErrorNote error={q.error} />
  const c = q.data
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">OPERATIONS</div>
        <h1>Cost and transparency</h1>
        <p>Dataset processing, evidence checks and model usage.</p>
      </header>
      <div className="stats-grid">
        {[
          {
            name: 'Input records processed',
            value: c.processed_records,
            icon: Layers3,
          },
          { name: 'Duplicates removed', value: c.duplicates, icon: Copy },
          {
            name: 'Supported claims',
            value: c.verified_claims,
            icon: BookOpenCheck,
          },
          {
            name: 'Conflicting claims',
            value: c.conflicting_claims,
            icon: ShieldAlert,
          },
        ].map((v) => (
          <Card className="stat" key={v.name}>
            <v.icon size={19} />
            <strong>{count(v.value)}</strong>
            <span>{v.name}</span>
          </Card>
        ))}
      </div>
      <div className="section-heading">
        <h2>Processing costs</h2>
        <Badge>USD</Badge>
      </div>
      <Card>
        <dl className="metric-list">
          {[
            ['Measured API charges', dollars(c.measured_usd)],
            ['Estimated API and compute costs', dollars(c.estimated_usd)],
            [
              'Compute estimate included above',
              dollars(c.compute_estimate_usd),
            ],
            [
              'Configured compute price per hour',
              dollars(c.compute_usd_per_hour),
            ],
            [
              'Simulated cost at 10× dataset volume',
              dollars(c.projected_10x_usd),
            ],
            ['Cost per story', dollars(c.cost_per_story)],
            ['Cost per generated briefing', dollars(c.cost_per_briefing)],
          ].map(([k, v]) => (
            <div key={k}>
              <dt>{k}</dt>
              <dd>{v}</dd>
            </div>
          ))}
        </dl>
        <p className="muted">{c.pricing_note}</p>
        {c.unpriced_events > 0 && (
          <p className="notice amber">
            {count(c.unpriced_events)} usage events have no price. Reported
            costs exclude their unknown charges.
          </p>
        )}
      </Card>
      <div className="form-grid">
        <Card>
          <h2>Measured usage</h2>
          <dl className="metric-list">
            {[
              ['Articles retained after deduplication', c.articles],
              ['Stories created', c.stories],
              ['Embedding calls', c.embedding_calls],
              ['Transcription calls', c.stt_calls],
              ['LLM calls', c.llm_calls],
              ['Input tokens', c.input_tokens],
              ['Output tokens', c.output_tokens],
              ['TTS characters', c.tts_characters],
            ].map(([k, v]) => (
              <div key={k}>
                <dt>{k}</dt>
                <dd>{count(Number(v))}</dd>
              </div>
            ))}
          </dl>
        </Card>
        <Card>
          <h2>
            <Timer size={18} /> Processing time
          </h2>
          <dl className="metric-list">
            {Object.entries(c.stage_seconds).map(([k, v]) => (
              <div key={k}>
                <dt>{label(k)}</dt>
                <dd>{v.toFixed(2)} s</dd>
              </div>
            ))}
          </dl>
          {!Object.keys(c.stage_seconds).length && (
            <p className="muted">No timed stages recorded yet.</p>
          )}
        </Card>
      </div>
    </>
  )
}
