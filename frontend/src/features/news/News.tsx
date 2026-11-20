import { useState } from 'react'
import { useInfiniteQuery, useMutation } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import {
  Search,
  Layers3,
  Headphones,
  AudioLines,
  MessagesSquare,
  ExternalLink,
  SlidersHorizontal,
  ThumbsUp,
  ThumbsDown,
} from 'lucide-react'
import { api, label, niceDate, useApi, queryClient } from '../../api/client'
import type { Health } from '../../api/client'
import type { Story, StoryDetail, StoryPage, Topic } from '../../api/types'
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Empty,
  ErrorNote,
  Loading,
  SourceCitation,
  Tabs,
  VerificationIndicator,
} from '../../components/UI'
import { SignalArt } from '../../components/SignalArt'
export const topicVariant = (s: Story) =>
  s.topics.some((t) => ['finance', 'economy'].includes(t))
    ? 0
    : s.topics.some((t) =>
          ['artificial_intelligence', 'technology'].includes(t)
        )
      ? 1
      : (s.category.length % 2) + 2
export function StoryCard({ story: s }: { story: Story }) {
  return (
    <Link to={'/stories/' + s.id} className="story-card">
      <div className={'story-art art-' + topicVariant(s)}>
        <SignalArt mini variant={topicVariant(s)} />
        <AudioLines size={18} />
      </div>
      <div className="story-content">
        <span className="kicker">
          {label(s.category || s.topics[0] || 'News')}
        </span>
        <h3>{s.title}</h3>
        <div className="metadata">
          <Layers3 size={14} />
          {s.source_count} {s.source_count === 1 ? 'source' : 'sources'}
          <span>·</span>
          {niceDate(s.event_at)}
          {s.is_synthetic && (
            <>
              <span>·</span>Synthetic
            </>
          )}
        </div>
      </div>
      {s.importance >= 0.75 && (
        <span className="priority">High importance</span>
      )}
    </Link>
  )
}
export function Explore() {
  const [search, setSearch] = useState(''),
    [topic, setTopic] = useState(''),
    [period, setPeriod] = useState('week'),
    [sort, setSort] = useState('recent')
  const topics = useApi<Topic[]>('/topics')
  const health = useApi<Health>('/health')
  const query = useInfiniteQuery({
    queryKey: ['stories', search, topic, period, sort, health.data?.news_reference_time],
    initialPageParam: '',
    queryFn: ({ pageParam, signal }) => {
      const now = health.data?.news_reference_time ? new Date(health.data.news_reference_time) : new Date()
      now.setDate(now.getDate() - ({ day: 1, week: 7, month: 30 }[period] || 7))
      const params = new URLSearchParams({
        date_from: now.toISOString(),
        limit: '40',
        sort,
      })
      if (search.trim()) params.set('search', search.trim())
      if (topic) params.set('topic', topic)
      if (pageParam) params.set('cursor', pageParam)
      return api<StoryPage>('/stories?' + params, 'GET', undefined, signal)
    },
    getNextPageParam: (p) => p.next_cursor ?? undefined,
  })
  const stories = query.data?.pages.flatMap((p) => p.items) || []
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">NEWS DESK</div>
        <h1>Explore stories</h1>
      </header>
      <Card className="filters">
        <label className="search">
          <Search size={19} />
          <input
            type="search"
            placeholder="Search stories"
            aria-label="Search stories"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </label>
        <div className="filter-row">
          <Tabs
            value={period}
            onChange={setPeriod}
            options={[
              { id: 'day', name: 'Day' },
              { id: 'week', name: 'Week' },
              { id: 'month', name: 'Month' },
            ]}
          />
          <Dropdown label="Topic" value={topic} onChange={setTopic}>
            <option value="">All topics</option>
            {topics.data?.map((t) => (
              <option key={t.name} value={t.name}>
                {label(t.name)}
              </option>
            ))}
          </Dropdown>
          <Dropdown label="Sort stories" value={sort} onChange={setSort}>
            <option value="recent">Most recent</option>
            <option value="importance">Importance</option>
          </Dropdown>
        </div>
      </Card>
      <div className="section-heading">
        <h2>Story feed</h2>
        <SlidersHorizontal size={18} />
      </div>
      <ErrorNote error={query.error || topics.error} />
      {query.isPending ? (
        <Loading />
      ) : !stories.length ? (
        <Empty>No matching stories for this period.</Empty>
      ) : (
        <div className="story-list">
          {stories.map((s) => (
            <StoryCard key={s.id} story={s} />
          ))}
        </div>
      )}
      {query.hasNextPage && (
        <Button
          variant="outline"
          disabled={query.isFetchingNextPage}
          onClick={() => query.fetchNextPage()}
        >
          Load more
        </Button>
      )}
    </>
  )
}
export function StoryView() {
  const { id } = useParams(),
    q = useApi<StoryDetail>('/stories/' + id)
  const feedback = useMutation({
    mutationFn: (score: number) => api('/feedback/' + id, 'PUT', { score }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        predicate: (q) => String(q.queryKey[0]).startsWith('/recommendations'),
      }),
  })
  if (q.isPending) return <Loading />
  if (!q.data) return <ErrorNote error={q.error} />
  const s = q.data
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">
          {label(s.category)} / {niceDate(s.event_at)}
        </div>
        <h1>{s.title}</h1>
        <div className="metadata">
          <Layers3 size={16} />
          {s.source_count} sources · {s.article_count} articles{' '}
          {s.is_synthetic && <Badge>Synthetic edition</Badge>}
        </div>
      </header>
      <div className="action-row">
        <Link className="btn primary" to={'/briefings/new?story=' + s.id}>
          <Headphones size={17} />
          Make a briefing
        </Link>
        <Link className="btn outline" to={'/assistant?story=' + s.id}>
          <MessagesSquare size={17} />
          Ask about this story
        </Link>
      </div>
      <Card>
        <h2>Story summary</h2>
        <p className="body-copy">{s.summary}</p>
        <div className="feedback">
          <span>Adjust recommendations</span>
          <Button
            variant="quiet"
            disabled={feedback.isPending}
            onClick={() => feedback.mutate(1)}
          >
            <ThumbsUp size={15} />
            More like this
          </Button>
          <Button
            variant="quiet"
            disabled={feedback.isPending}
            onClick={() => feedback.mutate(-1)}
          >
            <ThumbsDown size={15} />
            Less like this
          </Button>
          {feedback.isSuccess && <small role="status">Saved</small>}
        </div>
        <ErrorNote error={feedback.error} />
      </Card>
      <div className="section-heading">
        <h2>Source comparison</h2>
        <Badge>{s.disagreements.length} disagreements</Badge>
      </div>
      {s.disagreements.map((d) => (
        <div key={d.id} className="notice amber">
          {d.description}
        </div>
      ))}
      {!s.disagreements.length && (
        <p className="muted">
          No disagreement flagged in the available reporting.
        </p>
      )}
      <div className="section-heading">
        <h2>Facts and evidence</h2>
      </div>
      {s.facts.length === 0 && <Empty>No extracted facts.</Empty>}
      {s.facts.map((f) => (
        <Card key={f.id} className="fact">
          <VerificationIndicator status={f.status} />
          <p>{f.text}</p>
          <details>
            <summary>
              {f.evidence.length} evidence{' '}
              {f.evidence.length === 1 ? 'excerpt' : 'excerpts'}
            </summary>
            {f.evidence.map((e, i) => (
              <SourceCitation
                key={i}
                citation={{
                  article_id: e.article_id,
                  source: e.source_name,
                  url: e.url,
                  excerpt: e.excerpt,
                  is_synthetic: e.is_synthetic,
                }}
              />
            ))}
          </details>
        </Card>
      ))}
      <div className="section-heading">
        <h2>Original reporting</h2>
      </div>
      {s.articles.map((a) => (
        <div className="report" key={a.id}>
          <strong>{a.title}</strong>
          <span>
            {a.source_name} · {a.language.toUpperCase()} ·{' '}
            {niceDate(a.published_at)}
          </span>
          {!a.is_synthetic && /^https?:\/\//i.test(a.url) && (
            <a href={a.url} rel="noreferrer" target="_blank">
              Read article <ExternalLink size={14} />
            </a>
          )}
        </div>
      ))}
    </>
  )
}
