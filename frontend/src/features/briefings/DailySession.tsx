import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Mic, MicOff, Pause, Play, Square } from 'lucide-react'
import {
  api,
  request,
  clockTime,
  queryClient,
  useBriefingAudio,
  useApi,
} from '../../api/client'
import type { Health } from '../../api/client'
import type { BriefingDetail, Conversation, Message } from '../../api/types'
import { ErrorNote, SourceCitation } from '../../components/UI'
import { LiveMicrophone } from './liveMicrophone'

export function DailySession({
  selectedId = '',
  playRequest = 0,
}: {
  selectedId?: string
  playRequest?: number
}) {
  const health = useApi<Health>('/health')
  const daily = useQuery({
    queryKey: ['daily-edition'],
    queryFn: () => {
      const previous = queryClient.getQueryData<BriefingDetail>([
        'daily-edition',
      ])
      return previous && !['completed', 'failed'].includes(previous.status)
        ? api<BriefingDetail>('/briefings/' + previous.id)
        : api<BriefingDetail>('/briefings/daily', 'POST')
    },
    staleTime: Infinity,
    refetchInterval: (q) =>
      q.state.data && !['completed', 'failed'].includes(q.state.data.status)
        ? 1500
        : 60000,
  })
  const custom = useQuery({
    queryKey: ['live-custom', selectedId],
    enabled: !!selectedId,
    queryFn: () => api<BriefingDetail>('/briefings/' + selectedId),
    refetchInterval: (q) =>
      q.state.data && !['completed', 'failed'].includes(q.state.data.status)
        ? 1500
        : false,
  })
  const edition = selectedId ? custom.data : daily.data
  const retry = useMutation({
    mutationFn: () => api('/briefings/' + edition?.id + '/retry', 'POST'),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['daily-edition'] })
      queryClient.invalidateQueries({ queryKey: ['live-custom', selectedId] })
    },
  })
  const audio = useBriefingAudio(
    edition?.status === 'completed' ? edition.id : undefined,
  )
  const url = audio.data?.url || ''
  const [playing, setPlaying] = useState(false)
  const [answerPlaying, setAnswerPlaying] = useState(false)
  const [position, setPosition] = useState(0)
  const [listening, setListening] = useState(false)
  const [responding, setResponding] = useState(false)
  const [phase, setPhase] = useState('')
  const [error, setError] = useState('')
  const [reply, setReply] = useState<Message | null>(null)
  const [transcript, setTranscript] = useState('')
  const narration = useRef<HTMLAudioElement>(null)
  const answer = useRef<HTMLAudioElement>(null)
  const microphone = useRef<LiveMicrophone | null>(null)
  const conversation = useRef<Promise<Conversation> | null>(null)
  const turn = useRef(0)
  const controller = useRef<AbortController | null>(null)
  const answerUrl = useRef('')
  const mounted = useRef(true)
  const editionRef = useRef(edition)
  const briefingContext = useRef(true)
  editionRef.current = edition
  const bufferedId = audio.data ? edition?.id : undefined
  const lastStarted = useRef(0)

  useEffect(() => {
    stopSession()
    setReply(null)
    setTranscript('')
    setPosition(0)
    conversation.current = null
    briefingContext.current = true
  }, [edition?.id])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      microphone.current?.stop()
      controller.current?.abort()
      if (answerUrl.current) URL.revokeObjectURL(answerUrl.current)
    }
  }, [])

  useEffect(() => {
    if (
      url &&
      bufferedId === edition?.id &&
      playRequest > lastStarted.current
    ) {
      lastStarted.current = playRequest
      play()
    }
  }, [url, bufferedId, edition?.id, playRequest])
  function cancelTurn() {
    turn.current++
    controller.current?.abort()
    answer.current?.pause()
    narration.current?.pause()
    setPlaying(false)
    setResponding(false)
    setPhase('Listening…')
  }
  function stopSession() {
    cancelTurn()
    microphone.current?.stop()
    microphone.current = null
    setListening(false)
    setPhase('')
  }
  async function startListening() {
    if (microphone.current) return
    const mic = new LiveMicrophone(
      cancelTurn,
      (blob) => void respond(blob),
      (message) => {
        setError(message)
        setListening(false)
      },
    )
    microphone.current = mic
    try {
      await mic.start()
      setError('')
      if (mounted.current) {
        setListening(true)
        setPhase('Listening while your briefing plays')
      }
    } catch (e) {
      mic.stop()
      microphone.current = null
      setListening(false)
      setError(e instanceof Error ? e.message : 'Microphone access failed.')
    }
  }
  async function respond(input: Blob | string) {
    const current = ++turn.current
    controller.current?.abort()
    const abort = (controller.current = new AbortController())
    const valid = () =>
      mounted.current && current === turn.current && !abort.signal.aborted
    narration.current?.pause()
    answer.current?.pause()
    setResponding(true)
    setError('')
    setPhase('Understanding your question…')
    try {
      const b = editionRef.current
      if (!b) return
      if (!conversation.current)
        conversation.current = api<Conversation>('/conversations', 'POST', {
          briefing_id: b.id,
        })
      let conv: Conversation
      try {
        conv = await conversation.current
      } catch (e) {
        conversation.current = null
        throw e
      }
      if (!valid()) return
      const data = typeof input === 'string' ? { text: input } : new FormData()
      const active = b.segments.find(
        (s) =>
          s.story_id &&
          s.start_seconds <= (narration.current?.currentTime || 0) &&
          s.end_seconds > (narration.current?.currentTime || 0),
      )
      if (typeof input !== 'string' && data instanceof FormData) {
        data.set('file', input, 'utterance.' + (input.type.includes('mp4') ? 'm4a' : 'webm'))
        if (active?.story_id && briefingContext.current) data.set('story_id', active.story_id)
      }
      const message = await api<Message & { transcription?: string }>(
        '/conversations/' + conv.id + (typeof input === 'string' ? '/messages' : '/audio'),
        'POST',
        data,
        abort.signal,
      )
      if (!valid()) return
      setReply(message)
      briefingContext.current = false
      setTranscript(message.transcription || (typeof input === 'string' ? input : ''))
      if (
        ['SKIP_STORY', 'SELECT_STORY'].includes(
          String(message.action?.type || ''),
        ) &&
        message.story_id
      ) {
        const target = b.segments.find((s) => s.story_id === message.story_id)
        if (target && narration.current) {
          narration.current.currentTime = target.start_seconds
          setPosition(target.start_seconds)
        }
      }
      if (message.action?.type === 'STOP_PLAYBACK') {
        setPhase('Paused. Say “continue” to resume.')
        return
      }
      if (message.action?.type === 'RESUME_PLAYBACK') {
        await narration.current?.play()
        setPhase('Listening while your briefing plays')
        return
      }
      setPhase('Preparing a spoken answer…')
      const response = await request(
        '/conversations/' + conv.id + '/messages/' + message.id + '/audio',
        'GET',
        undefined,
        abort.signal,
      )
      const content = await response.blob()
      if (!valid()) return
      if (answerUrl.current) URL.revokeObjectURL(answerUrl.current)
      answerUrl.current = URL.createObjectURL(content)
      if (answer.current) {
        answer.current.src = answerUrl.current
        await answer.current.play()
      }
      setPhase('Answering · you can interrupt')
    } catch (e) {
      if (valid()) {
        setError(e instanceof Error ? e.message : 'Voice response failed')
        setPhase('Listening · retry your question or resume the briefing')
      }
    } finally {
      if (valid()) setResponding(false)
    }
  }
  function play() {
    setError('')
    if (playing || answerPlaying) {
      answer.current?.pause()
      narration.current?.pause()
      setPlaying(false)
      return
    }
    // Playback uses the buffered file directly inside the user's click event.
    answer.current?.pause()
    controller.current?.abort()
    turn.current++
    void narration.current?.play().catch((e) => setError(e.message))
    void startListening()
  }
  const audible = playing || answerPlaying
  return (
    <section className="listening-hero" aria-label="News player">
      <div className="listening-date">
        {(health.data?.news_reference_time ? new Date(health.data.news_reference_time) : new Date()).toLocaleDateString('en', {
          weekday: 'long',
          month: 'long',
          day: 'numeric',
        })}
      </div>
      <h1>
        {selectedId
          ? edition?.period === 'week'
            ? 'This week.'
            : edition?.title || 'Your briefing.'
          : health.data?.news_reference_time ? 'Archive briefing.' : "Today's news."}
      </h1>
      <p className="listening-subtitle">
        {edition?.status === 'completed'
          ? (edition.period === 'week' ? 'Weekly briefing' : edition.items.length + ' top stories') +
            ' · ' +
            clockTime(edition.duration_seconds)
          : edition?.status === 'failed'
            ? 'Your edition needs attention.'
            : edition?.status === 'processing'
              ? 'Writing and checking your briefing…'
              : edition?.status === 'script_ready' || edition?.status === 'audio_generating'
                ? 'Creating your audio…'
                : 'Your edition is queued for preparation…'}
      </p>
      <audio
        ref={narration}
        src={url || undefined}
        preload="auto"
        onPlay={() => {
          briefingContext.current = true
          setPlaying(true)
        }}
        onPause={() => setPlaying(false)}
        onTimeUpdate={() => setPosition(narration.current?.currentTime || 0)}
        onEnded={() => {
          setPlaying(false)
          setPhase(listening ? 'Ask about any story.' : 'Briefing finished.')
        }}
      />
      <audio
        ref={answer}
        onPlay={() => setAnswerPlaying(true)}
        onPause={() => setAnswerPlaying(false)}
        onEnded={() => {
          setAnswerPlaying(false)
          setPhase('Ask more, or say “continue”.')
        }}
      />
      <button
        className={'main-play' + (audible ? ' playing' : '')}
        disabled={!url || bufferedId !== edition?.id}
        onClick={play}
        aria-label={audible ? 'Pause daily briefing' : 'Play daily briefing'}
      >
        {audible ? (
          <Pause size={34} fill="currentColor" />
        ) : (
          <Play size={34} fill="currentColor" />
        )}
      </button>
      <p role="status" className="session-status">
        {phase || 'Ask questions while you listen.'}
      </p>
      <div className="compact-timeline">
        <span>{clockTime(position)}</span>
        <input
          aria-label="Seek daily briefing"
          disabled={!url}
          type="range"
          min={0}
          max={edition?.duration_seconds || 0}
          step={0.1}
          value={position}
          onChange={(e) => {
            briefingContext.current = true
            if (narration.current)
              narration.current.currentTime = Number(e.target.value)
            setPosition(Number(e.target.value))
          }}
        />
        <span>{clockTime(edition?.duration_seconds || 0)}</span>
      </div>
      <div className="session-tools">
        <button disabled={!url || responding} onClick={() => void respond('More news')}>
          {responding ? 'Preparing answer…' : 'More news'}
        </button>
        <button
          disabled={!url}
          className={'microphone-control' + (listening ? ' active' : '')}
          onClick={() => (listening ? stopSession() : void startListening())}
          aria-label={listening ? 'Turn microphone off' : 'Turn microphone on'}
          aria-pressed={listening}
        >
          {listening ? <Mic size={15} /> : <MicOff size={15} />}{' '}
          {listening ? 'Listening' : 'Voice chat'}
        </button>
        {edition?.status === 'completed' && (
          <Link to={'/briefings/' + edition.id}>Transcript & sources</Link>
        )}
        {listening && (
          <button
            className="session-end"
            onClick={stopSession}
            aria-label="End voice session"
          >
            <Square size={12} /> End
          </button>
        )}
      </div>
      <span className="listening-disclosure">
        AI narration ·{' '}
        {listening
          ? 'Microphone active'
          : 'Allow microphone access to ask questions.'}
      </span>
      {edition?.status === 'failed' && (
        <>
          <ErrorNote error={edition.error} />
          <button className="btn outline" disabled={retry.isPending} onClick={() => retry.mutate()}>
            {retry.isPending ? 'Retrying…' : 'Retry preparation'}
          </button>
        </>
      )}
      <ErrorNote error={error || daily.error || custom.error || audio.error || retry.error} />
      {reply && (
        <div className="live-response">
          <p className="muted">You · {transcript}</p>
          <p>{reply.text}</p>
          {reply.citations.length > 0 && (
            <details>
              <summary>Sources ({reply.citations.length})</summary>
              {reply.citations.map((c, i) => (
                <SourceCitation key={i} citation={c} />
              ))}
            </details>
          )}
          <button
            className="text-link"
            onClick={() => {
              cancelTurn()
              void narration.current?.play()
              setPhase('Listening')
            }}
          >
            Resume briefing
          </button>
        </div>
      )}
    </section>
  )
}
