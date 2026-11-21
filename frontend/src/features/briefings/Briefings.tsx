import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useQuery, useMutation } from '@tanstack/react-query'
import {
  AudioLines,
  ChevronRight,
  FileText,
  Headphones,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  ShieldCheck,
  Mic2,
  MessagesSquare,
} from 'lucide-react'
import {
  api,
  clockTime,
  getToken,
  label,
  niceDate,
  queryClient,
  request,
  useApi,
} from '../../api/client'
import type {
  Briefing,
  BriefingDetail,
  Preferences,
  Segment,
  Story,
  Topic,
  Voice,
} from '../../api/types'
import {
  Badge,
  Button,
  Card,
  Dropdown,
  Empty,
  ErrorNote,
  Loading,
  SourceCitation,
  VerificationIndicator,
} from '../../components/UI'
import { SignalArt } from '../../components/SignalArt'
import { usePlayer } from '../../stores/player'
export function VoiceSelector({
  voices,
  value,
  onChange,
}: {
  voices: Voice[]
  value: string
  onChange: (v: string) => void
}) {
  return (
    <Dropdown label="Voice style" value={value} onChange={onChange}>
      {voices.map((v) => (
        <option value={v.id} key={v.id} disabled={v.locked}>
          {v.name}{v.locked ? ' · Premium' : ''}
        </option>
      ))}
    </Dropdown>
  )
}
export function BriefingForm() {
  const prefs = useApi<Preferences>('/users/me/preferences'),
    voices = useApi<Voice[]>('/voices'),
    topics = useApi<Topic[]>('/topics')
  const [search] = useSearchParams(),
    [period, setPeriod] = useState(search.get('period') === 'day' ? 'day' : 'week'),
    [topic, setTopic] = useState(''),
    [minutes, setMinutes] = useState<number>(),
    [language, setLanguage] = useState(''),
    [voice, setVoice] = useState('')
  const [selection, setSelection] = useState<string[]>(() =>
    search.getAll('story')
  )
  const stories = useApi<Story[]>('/recommendations?period=' + period),
    navigate = useNavigate()
  const selectedStory = useApi<Story>(
    '/stories/' + selection[0],
    selection.length === 1 && !stories.data?.some((s) => s.id === selection[0])
  )
  const candidates = stories.data || []
  const options =
    selectedStory.data &&
    !candidates.some((s) => s.id === selectedStory.data.id)
      ? [selectedStory.data, ...candidates]
      : candidates
  const make = useMutation({
    mutationFn: () =>
      api<{ briefing_id: string }>('/briefings', 'POST', {
        period,
        topic: topic || null,
        duration_minutes: minutes ?? prefs.data?.duration_minutes,
        language: language || prefs.data?.language,
        voice_profile_id: voice || prefs.data?.voice_profile_id,
        selected_story_ids: selection,
      }),
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['/briefings'] })
      navigate('/briefings/' + r.briefing_id)
    },
  })
  if (prefs.isPending) return <Loading />
  if (!prefs.data) return <ErrorNote error={prefs.error} />
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">AUDIO STUDIO</div>
        <h1>Make a briefing</h1>
        <p>
          Choose a listening window and we’ll rank the available stories for
          you.
        </p>
      </header>
      <Card>
        <form
          className="form-stack"
          onSubmit={(e) => {
            e.preventDefault()
            make.mutate()
          }}
        >
          <div className="form-grid">
            <Dropdown
              label="Coverage"
              value={period}
              onChange={(v) => {
                setPeriod(v)
                setSelection([])
              }}
            >
              <option value="day">Last day</option>
              <option value="week">Last week</option>
              <option value="month">Last month</option>
            </Dropdown>
            <Dropdown label="Topic" value={topic} onChange={setTopic}>
              <option value="">All topics</option>
              {topics.data?.map((t) => (
                <option key={t.name} value={t.name}>
                  {label(t.name)}
                </option>
              ))}
            </Dropdown>
            <label className="field">
              Target minutes
              <input
                type="number"
                min={1}
                max={30}
                value={minutes ?? prefs.data.duration_minutes}
                onChange={(e) => setMinutes(Number(e.target.value))}
              />
            </label>
            <Dropdown
              label="Language"
              value={language || prefs.data.language}
              onChange={setLanguage}
            >
              <option value="en">English</option>
              <option value="de">German</option>
              <option value="nl">Dutch</option>
            </Dropdown>
            <VoiceSelector
              voices={voices.data || []}
              value={voice || prefs.data.voice_profile_id}
              onChange={setVoice}
            />
          </div>
          <fieldset className="choices">
            <legend>Include specific stories</legend>
            <p className="muted">Leave empty for a personalized selection.</p>
            {options.map((s) => (
              <label key={s.id} className="check">
                <input
                  type="checkbox"
                  checked={selection.includes(s.id)}
                  onChange={(e) =>
                    setSelection((prev) =>
                      e.target.checked
                        ? [...prev, s.id]
                        : prev.filter((id) => id !== s.id)
                    )
                  }
                />
                {s.title}
              </label>
            ))}
          </fieldset>
          <ErrorNote
            error={make.error || voices.error || topics.error || stories.error}
          />
          <Button disabled={make.isPending}>
            <AudioLines size={17} />
            {make.isPending ? 'Requesting…' : 'Generate audio briefing'}
          </Button>
        </form>
      </Card>
    </>
  )
}
export function History() {
  const q = useApi<Briefing[]>('/briefings')
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">YOUR LIBRARY</div>
        <h1>Briefing history</h1>
      </header>
      <Link className="btn primary" to="/briefings/new">
        <Headphones size={17} />
        Make a briefing
      </Link>
      <div className="history-list">
        <ErrorNote error={q.error} />
        {q.isPending ? (
          <Loading />
        ) : q.data?.length ? (
          q.data.map((b) => (
            <Link className="history-row" key={b.id} to={'/briefings/' + b.id}>
              <span className="round-icon">
                <AudioLines size={20} />
              </span>
              <div>
                <h3>{b.title}</h3>
                <span className="metadata">
                  {niceDate(b.created_at)} · {b.language.toUpperCase()} ·{' '}
                  {clockTime(b.duration_seconds)}
                </span>
              </div>
              <Badge>{label(b.status)}</Badge>
              <ChevronRight size={16} />
            </Link>
          ))
        ) : (
          <Empty>Your generated briefings will appear here.</Empty>
        )}
      </div>
    </>
  )
}
const terminal = (s?: string) => s === 'completed' || s === 'failed'
export function useBriefing(id: string) {
  const q = useQuery({
    queryKey: ['briefing', id],
    queryFn: ({ signal }) =>
      api<BriefingDetail>('/briefings/' + id, 'GET', undefined, signal),
    refetchInterval: (q) => (terminal(q.state.data?.status) ? false : 2000),
    staleTime: 0,
  })
  const done = terminal(q.data?.status)
  useEffect(() => {
    if (done) return
    let stopped = false,
      ws: WebSocket | undefined,
      retry: ReturnType<typeof setTimeout>,
      attempts = 0
    const open = () => {
      if (stopped) return
      ws = new WebSocket(
        (location.protocol === 'https:' ? 'wss:' : 'ws:') +
          '//' +
          location.host +
          '/api/v1/ws/briefings/' +
          id
      )
      ws.onopen = () => ws?.send(JSON.stringify({ token: getToken() }))
      ws.onmessage = () => {
        queryClient.invalidateQueries({ queryKey: ['briefing', id] })
      }
      ws.onclose = () => {
        if (!stopped)
          retry = setTimeout(
            open,
            Math.min(15000, 1000 * 2 ** Math.min(++attempts, 4))
          )
      }
    }
    open()
    return () => {
      stopped = true
      clearTimeout(retry)
      ws?.close()
    }
  }, [id, done])
  return q
}
export function activeSegment(segments: Segment[], time: number) {
  return segments.find((s) => time >= s.start_seconds && time < s.end_seconds)
}
export function AudioPlayer({ briefing: b }: { briefing: BriefingDetail }) {
  const ref = useRef<HTMLAudioElement>(null),
    { speed, setSpeed, setActive } = usePlayer()
  const [url, setUrl] = useState(''),
    [error, setError] = useState(''),
    [duration, setDuration] = useState(0),
    [time, setTime] = useState(0),
    [playing, setPlaying] = useState(false),
    [show, setShow] = useState(true)
  const [attempt, reload] = useState(0)
  useEffect(() => {
    const controller = new AbortController()
    let owned = ''
    setUrl('')
    setError('')
    setTime(0)
    setPlaying(false)
    setActive(b.id)
    request(
      '/briefings/' + b.id + '/audio',
      'GET',
      undefined,
      controller.signal
    )
      .then((r) => r.blob())
      .then((blob) => {
        if (!controller.signal.aborted) {
          owned = URL.createObjectURL(blob)
          setUrl(owned)
        }
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e.message)
      })
    return () => {
      controller.abort()
      if (owned) URL.revokeObjectURL(owned)
    }
  }, [b.id, attempt, setActive])
  useEffect(() => {
    if (ref.current) ref.current.playbackRate = speed
  }, [speed, url])
  const recorded = useRef(new Set<string>())
  const seconds = duration || b.duration_seconds || 0,
    active = activeSegment(b.segments, time)
  const currentStory = active?.story_id
  useEffect(() => {
    if (!playing || !currentStory || recorded.current.has(currentStory)) return
    const timer = window.setTimeout(() => {
      recorded.current.add(currentStory)
      request('/listening-history/' + currentStory, 'PUT')
        .then(() =>
          queryClient.invalidateQueries({
            predicate: (q) =>
              String(q.queryKey[0]).startsWith('/recommendations'),
          })
        )
        .catch(() => {
          recorded.current.delete(currentStory)
        })
    }, 1000)
    return () => window.clearTimeout(timer)
  }, [playing, currentStory])
  const chapters = b.items
    .map((i) => ({
      item: i,
      seg: b.segments.find((s) => s.story_id === i.story_id),
    }))
    .filter(
      (c): c is { item: (typeof b.items)[number]; seg: Segment } => !!c.seg
    )
  const seek = (n: number) => {
    if (ref.current && url) {
      ref.current.currentTime = n
      setTime(n)
    }
  }
  const play = async () => {
    if (!ref.current) return
    if (playing) ref.current.pause()
    else
      try {
        await ref.current.play()
      } catch {
        setError('Playback could not start. Reload audio and try again.')
      }
  }
  return (
    <>
      <Card className="player">
        <div className="player-cover">
          <SignalArt mini />
          <Headphones size={20} />
        </div>
        <div className="player-top">
          <div className="eyebrow">AUDIO PLAYER</div>
          <h2>{b.title}</h2>
          <span className="metadata">
            {b.items.length} stories · {b.language.toUpperCase()}
          </span>
        </div>
        <audio
          src={url || undefined}
          ref={ref}
          preload="metadata"
          onLoadedMetadata={(e) => setDuration(e.currentTarget.duration)}
          onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onEnded={() => setPlaying(false)}
          onError={() => {
            if (url) setError('This audio file could not be played.')
          }}
        />
        <div className="transport">
          <label className="seek">
            <span>{clockTime(time)}</span>
            <input
              aria-label="Seek audio"
              type="range"
              min={0}
              max={seconds || 1}
              step=".1"
              value={Math.min(time, seconds)}
              disabled={!url}
              onChange={(e) => seek(Number(e.target.value))}
            />
            <span>{clockTime(seconds)}</span>
          </label>
          <div className="player-buttons">
            <button
              className="icon"
              aria-label="Previous story"
              disabled={!url || !chapters.length}
              onClick={() =>
                seek(
                  [...chapters]
                    .reverse()
                    .find((c) => c.seg.start_seconds < time - 1)?.seg
                    .start_seconds || 0
                )
              }
            >
              <SkipBack size={19} />
            </button>
            <button
              className="play-circle"
              aria-label={playing ? 'Pause audio' : 'Play audio'}
              disabled={!url}
              onClick={play}
            >
              {playing ? <Pause size={21} /> : <Play size={21} />}
            </button>
            <button
              className="icon"
              aria-label="Next story"
              disabled={
                !url || !chapters.some((c) => c.seg.start_seconds > time + 0.2)
              }
              onClick={() =>
                seek(
                  chapters.find((c) => c.seg.start_seconds > time + 0.2)!.seg
                    .start_seconds
                )
              }
            >
              <SkipForward size={19} />
            </button>
            <label className="speed">
              <select
                value={speed}
                onChange={(e) => setSpeed(Number(e.target.value))}
                aria-label="Playback speed"
              >
                {[0.75, 1, 1.25, 1.5, 2].map((n) => (
                  <option key={n} value={n}>
                    {n}×
                  </option>
                ))}
              </select>
            </label>
          </div>
        </div>
        {!url && !error && <Loading>Loading audio…</Loading>}
        {error && (
          <div>
            <ErrorNote error={error} />
            <Button variant="outline" onClick={() => reload((a) => a + 1)}>
              Reload audio
            </Button>
          </div>
        )}
      </Card>
      <p className="disclosure">
        <ShieldCheck size={16} />
        AI-generated narration. All factual claims are linked to their sources.
      </p>
      <div className="section-heading">
        <h2>Transcript and sources</h2>
        <button className="text-link" onClick={() => setShow(!show)}>
          <FileText size={15} />
          {show ? 'Hide' : 'Show'}
        </button>
      </div>
      {show &&
        b.segments.map((seg) => (
          <article
            className={'transcript ' + (seg.id === active?.id ? 'current' : '')}
            key={seg.id}
          >
            <button
              type="button"
              className="time-tag"
              disabled={!url}
              onClick={() => seek(seg.start_seconds)}
              aria-label={'Seek to ' + clockTime(seg.start_seconds)}
            >
              {clockTime(seg.start_seconds)}
            </button>
            <div>
              {seg.story_id && (
                <small className="kicker">
                  {
                    chapters.find((c) => c.item.story_id === seg.story_id)?.item
                      .title
                  }
                </small>
              )}
              <p>{seg.text}</p>
              {seg.citations.length > 0 && (
                <details open={seg.id === active?.id || undefined}>
                  <summary>
                    {seg.citations.length}{' '}
                    {seg.citations.length === 1 ? 'citation' : 'citations'}{' '}
                    <VerificationIndicator status={seg.verification_status} />
                  </summary>
                  {seg.citations.map((c, i) => (
                    <SourceCitation key={i} citation={c} />
                  ))}
                </details>
              )}
            </div>
          </article>
        ))}
      <Link className="btn outline" to={'/assistant?briefing=' + b.id}>
        <MessagesSquare size={16} />
        Discuss this briefing
      </Link>
    </>
  )
}
export function BriefingView() {
  const { id = '' } = useParams(),
    q = useBriefing(id)
  const retry = useMutation({
    mutationFn: () => api('/briefings/' + id + '/retry', 'POST'),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ['briefing', id] }),
  })
  if (q.isPending) return <Loading />
  if (!q.data) return <ErrorNote error={q.error} />
  const b = q.data
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">LISTENING ROOM / {niceDate(b.created_at)}</div>
        <h1>Your briefing</h1>
      </header>
      {b.status === 'completed' ? (
        <AudioPlayer briefing={b} />
      ) : (
        <Card>
          <Badge>{label(b.status)}</Badge>
          <h2>
            {b.status === 'failed'
              ? 'Generation stopped'
              : 'Preparing your audio'}
          </h2>
          {b.status === 'failed' ? (
            <>
              <ErrorNote
                error={b.error || 'This briefing could not be generated.'}
              />
              <Button
                variant="outline"
                disabled={retry.isPending}
                onClick={() => retry.mutate()}
              >
                Retry generation
              </Button>
              <ErrorNote error={retry.error} />
            </>
          ) : (
            <>
              <progress value={b.progress} max={100} />
              <p className="muted">{b.progress}% · Updates automatically</p>
            </>
          )}
        </Card>
      )}
    </>
  )
}
