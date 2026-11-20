import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Mic, MicOff, Pause, Play, LoaderCircle, RotateCcw } from 'lucide-react'
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
import { ErrorNote } from '../../components/UI'
import { LiveMicrophone } from './liveMicrophone'
import {
  RealtimeVoice,
  unlockVoiceAudio,
  type VoicePhase,
} from './realtimeVoice'
import { useElevenAgent, type AgentConversation } from '../voice/useElevenAgent'

export function DailySession({
  selectedId = '',
  playRequest = 0,
}: {
  selectedId?: string
  playRequest?: number
}) {
  const health = useApi<Health>('/health')
  const useAgent = health.data?.conversation_provider === 'elevenagents'
  const agent = useElevenAgent(useAgent)
  const live = useRef<AgentConversation | null>(null)
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
  const [voiceConnecting, setVoiceConnecting] = useState(false)
  const [hasAnswer, setHasAnswer] = useState(false)
  const narration = useRef<HTMLAudioElement>(null)
  const answer = useRef<HTMLAudioElement>(null)
  const microphone = useRef<LiveMicrophone | null>(null)
  const realtime = useRef<RealtimeVoice | null>(null)
  const voiceOutput = useRef<AudioContext | null>(null)
  const resumeAfterAnswer = useRef(false)
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
    setHasAnswer(false)
    setPosition(0)
    conversation.current = null
    briefingContext.current = true
  }, [edition?.id])
  useEffect(() => {
    mounted.current = true
    return () => {
      mounted.current = false
      microphone.current?.stop()
      realtime.current?.close()
      void voiceOutput.current?.close()
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
    setAnswerPlaying(false)
    setPhase('')
  }
  function stopAgent() {
    live.current = null
    void agent.stop()
    setListening(false)
    setAnswerPlaying(false)
  }
  function stopMicrophone() {
    if (useAgent) {
      stopAgent()
      return
    }
    microphone.current?.stop()
    microphone.current = null
    void realtime.current?.setMicrophone(false)
    setListening(false)
    // Muting input must never cancel a pending answer or stop either audio output.
  }
  function stopSession() {
    cancelTurn()
    stopMicrophone()
    realtime.current?.close()
    realtime.current = null
    resumeAfterAnswer.current = false
    setPhase('')
  }
  async function ensureConversation() {
    const b = editionRef.current
    if (!b) throw Error('The briefing is not ready yet.')
    if (!conversation.current)
      conversation.current = api<Conversation>('/conversations', 'POST', {
        briefing_id: b.id,
      })
    try {
      return await conversation.current
    } catch (error) {
      conversation.current = null
      throw error
    }
  }
  function currentStory() {
    if (!briefingContext.current) return undefined
    return (
      editionRef.current?.segments.find(
        (s) =>
          s.story_id &&
          s.start_seconds <= (narration.current?.currentTime || 0) &&
          s.end_seconds > (narration.current?.currentTime || 0),
      )?.story_id || undefined
    )
  }
  function pauseLocalAudio() {
    narration.current?.pause()
    answer.current?.pause()
    controller.current?.abort()
    turn.current++
    setPlaying(false)
    setAnswerPlaying(false)
  }
  function applyAction(message: Message) {
    briefingContext.current = false
    setHasAnswer(true)
    if (
      ['SKIP_STORY', 'SELECT_STORY'].includes(String(message.action?.type)) &&
      message.story_id
    ) {
      const target = editionRef.current?.segments.find(
        (s) => s.story_id === message.story_id,
      )
      if (target && narration.current) {
        narration.current.currentTime = target.start_seconds
        setPosition(target.start_seconds)
      }
    }
    resumeAfterAnswer.current =
      message.action?.type === 'RESUME_PLAYBACK' ||
      message.action?.type === 'SKIP_STORY'
  }
  async function realtimeConnection() {
    if (realtime.current && !realtime.current.disposed) return realtime.current
    const conv = await ensureConversation()
    if (!mounted.current) throw new DOMException('Aborted', 'AbortError')
    realtime.current?.close()
    const voice = new RealtimeVoice(
      conv.id,
      {
        phase: (value: VoicePhase) => {
          if (!mounted.current) return
          setVoiceConnecting(value === 'connecting')
          setResponding(value === 'thinking')
          setAnswerPlaying(value === 'speaking')
          if (value === 'speaking') {
            setHasAnswer(true)
            briefingContext.current = false
          }
          setPhase(
            value === 'connecting'
              ? 'Connecting voice…'
              : value === 'thinking'
                ? 'Thinking…'
                : value === 'speaking'
                  ? 'Speaking'
                  : '',
          )
        },
        interrupt: pauseLocalAudio,
        microphone: (value) => {
          if (mounted.current) setListening(value)
        },
        story: currentStory,
        action: applyAction,
        finished: () => {
          if (resumeAfterAnswer.current) {
            resumeAfterAnswer.current = false
            void narration.current?.play().catch((e) => setError(e.message))
          }
        },
        failed: (message) => {
          if (mounted.current) {
            setError(message)
            setResponding(false)
            setVoiceConnecting(false)
          }
        },
      },
      voiceOutput.current || undefined,
    )
    realtime.current = voice
    return voice
  }
  async function startAgent() {
    const briefingId = editionRef.current?.id
    if (!briefingId) return null
    if (live.current) return live.current
    pauseLocalAudio()
    setHasAnswer(true)
    const session = await agent.start(
      () => ({
        briefing_id: briefingId,
        playback_seconds: narration.current?.currentTime || 0,
      }),
      {
        onModeChange: ({ mode }) => setAnswerPlaying(mode === 'speaking'),
        onDisconnect: stopAgent,
        onError: setError,
        clientTools: {
          resume_sourcera_briefing: () => {
            const active = live.current
            window.setTimeout(() => {
              if (!active || active !== live.current) return
              stopAgent()
              setHasAnswer(false)
              void narration.current?.play().catch((e) => setError(e.message))
            }, 0)
            return 'Resuming the prepared briefing.'
          },
        },
      },
    )
    if (session) {
      live.current = session
      setListening(true)
    }
    return session
  }
  async function startListening() {
    if (!useAgent) voiceOutput.current = unlockVoiceAudio(voiceOutput.current)
    setError('')
    setVoiceConnecting(true)
    try {
      if (useAgent) {
        await startAgent()
        return
      }
      if (health.data?.realtime_voice) {
        const voice = await realtimeConnection()
        await voice.setMicrophone(true)
        return
      }
      if (microphone.current) return
      const mic = new LiveMicrophone(
        cancelTurn,
        (blob) => void respond(blob),
        (message) => {
          setError(message)
          setListening(false)
          microphone.current = null
        },
      )
      microphone.current = mic
      await mic.start()
      if (mounted.current && microphone.current === mic) setListening(true)
    } catch (e) {
      microphone.current?.stop()
      microphone.current = null
      realtime.current?.close()
      realtime.current = null
      setListening(false)
      setError(e instanceof Error ? e.message : 'Microphone access failed.')
    } finally {
      if (mounted.current) setVoiceConnecting(false)
    }
  }
  async function moreNews() {
    if (!useAgent) voiceOutput.current = unlockVoiceAudio(voiceOutput.current)
    setError('')
    if (useAgent) {
      live.current?.sendUserMessage(
        'Find other recent stories using get_more_sourcera_news.',
      )
      return
    }
    if (health.data?.realtime_voice) {
      try {
        const voice = await realtimeConnection()
        await voice.moreNews()
        return
      } catch (error) {
        setError(
          error instanceof Error
            ? error.message
            : 'Voice connection failed. Please try again.',
        )
        setVoiceConnecting(false)
        setResponding(false)
        return
      }
    }
    await respond('More news')
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
      const conv = await ensureConversation()
      if (!valid()) return
      const data = typeof input === 'string' ? { text: input } : new FormData()
      const active = b.segments.find(
        (s) =>
          s.story_id &&
          s.start_seconds <= (narration.current?.currentTime || 0) &&
          s.end_seconds > (narration.current?.currentTime || 0),
      )
      if (typeof input !== 'string' && data instanceof FormData) {
        data.set(
          'file',
          input,
          'utterance.' + (input.type.includes('mp4') ? 'm4a' : 'webm'),
        )
        if (active?.story_id && briefingContext.current)
          data.set('story_id', active.story_id)
      }
      const message = await api<Message & { transcription?: string }>(
        '/conversations/' +
          conv.id +
          (typeof input === 'string' ? '/messages' : '/audio'),
        'POST',
        data,
        abort.signal,
      )
      if (!valid()) return
      applyAction(message)
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
    if (useAgent && agent.status !== 'disconnected') {
      stopAgent()
      setHasAnswer(false)
      void narration.current?.play().catch((e) => setError(e.message))
      return
    }
    resumeAfterAnswer.current = false
    if (playing || answerPlaying) {
      answer.current?.pause()
      narration.current?.pause()
      realtime.current?.interrupt()
      setPlaying(false)
      return
    }
    // Playback uses the buffered file directly inside the user's click event.
    answer.current?.pause()
    controller.current?.abort()
    turn.current++
    realtime.current?.interrupt()
    setHasAnswer(false)
    setResponding(false)
    setPhase('')
    void narration.current?.play().catch((e) => setError(e.message))
    if (health.data?.realtime_voice) {
      voiceOutput.current = unlockVoiceAudio(voiceOutput.current)
      void realtimeConnection()
        .then(async (voice) => {
          await voice.connect()
          voice.warmup()
        })
        .catch(() => {
          // A failed warm-up must not interrupt the prepared briefing.
          if (realtime.current?.disposed) realtime.current = null
        })
    }
  }
  const audible = playing || answerPlaying
  return (
    <section className="listening-hero" aria-label="News player">
      <div className="listening-date">
        {(health.data?.news_reference_time
          ? new Date(health.data.news_reference_time)
          : new Date()
        ).toLocaleDateString('en', {
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
          : health.data?.news_reference_time
            ? 'Archive briefing.'
            : "Today's news."}
      </h1>
      <p className="listening-subtitle">
        {edition?.status === 'completed'
          ? (edition.period === 'week'
              ? 'Weekly briefing'
              : edition.items.length + ' top stories') +
            ' · ' +
            clockTime(edition.duration_seconds)
          : edition?.status === 'failed'
            ? 'Your edition needs attention.'
            : edition?.status === 'processing'
              ? 'Writing and checking your briefing…'
              : edition?.status === 'script_ready' ||
                  edition?.status === 'audio_generating'
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
          setPhase('')
          if (resumeAfterAnswer.current) {
            resumeAfterAnswer.current = false
            void narration.current?.play()
          }
        }}
      />
      <button
        aria-busy={responding}
        className={'main-play' + (audible ? ' playing' : '')}
        disabled={!url || bufferedId !== edition?.id}
        onClick={play}
        aria-label={audible ? 'Pause daily briefing' : 'Play daily briefing'}
      >
        {responding ? (
          <LoaderCircle className="spin" size={30} />
        ) : audible ? (
          <Pause size={34} fill="currentColor" />
        ) : (
          <Play size={34} fill="currentColor" />
        )}
      </button>
      <p role="status" className="session-status">
        {phase ||
          (listening
            ? 'Listening · ask a question'
            : playing
              ? 'Playing · microphone off'
              : hasAnswer
                ? 'Ask more, or resume your briefing.'
                : 'Press play. Make time for the world.')}
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
        <button
          disabled={
            !url ||
            !health.data ||
            responding ||
            voiceConnecting ||
            (useAgent && !listening)
          }
          onClick={() => void moreNews()}
        >
          More news
        </button>
        <button
          disabled={!url || !health.data || voiceConnecting}
          className={'microphone-control' + (listening ? ' active' : '')}
          onClick={() => (listening ? stopMicrophone() : void startListening())}
          aria-label={listening ? 'Turn microphone off' : 'Turn microphone on'}
          aria-pressed={listening}
        >
          {listening ? <Mic size={15} /> : <MicOff size={15} />}{' '}
          {voiceConnecting ? 'Connecting…' : listening ? 'Mic on' : 'Mic off'}
        </button>
        {hasAnswer && (
          <button
            onClick={() => {
              if (useAgent) stopAgent()
              realtime.current?.interrupt()
              cancelTurn()
              setHasAnswer(false)
              setPhase('')
              void narration.current?.play()
            }}
            aria-label="Resume briefing"
          >
            <RotateCcw size={13} /> Resume briefing
          </button>
        )}
      </div>
      <span className="listening-disclosure">
        AI narration ·{' '}
        {listening
          ? 'Microphone active'
          : useAgent
            ? 'Voice chat sends microphone audio and briefing context to ElevenLabs.'
            : 'Listen freely. Turn the mic on to join in.'}
      </span>
      {edition?.status === 'failed' && (
        <>
          <ErrorNote error={edition.error} />
          <button
            className="btn outline"
            disabled={retry.isPending}
            onClick={() => retry.mutate()}
          >
            {retry.isPending ? 'Retrying…' : 'Retry preparation'}
          </button>
        </>
      )}
      <ErrorNote
        error={
          error || daily.error || custom.error || audio.error || retry.error
        }
      />
    </section>
  )
}
