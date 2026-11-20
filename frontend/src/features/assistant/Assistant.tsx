import { useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { AudioLines, LoaderCircle, Mic, MicOff, Plus, Send } from 'lucide-react'
import { api, request, useApi, type Health } from '../../api/client'
import type { Conversation, Message, User } from '../../api/types'
import { Button, Card, ErrorNote } from '../../components/UI'
import {
  RealtimeVoice,
  unlockVoiceAudio,
  type VoicePhase,
} from '../briefings/realtimeVoice'
import { useElevenAgent, type AgentConversation } from '../voice/useElevenAgent'
import { LiveMicrophone } from '../briefings/liveMicrophone'

export function Assistant({ user }: { user: User }) {
  const [params] = useSearchParams()
  const storageKey = `sourcera.conversation.${user.id}.${params.get('story') || params.get('briefing') || 'general'}`
  return (
    <VoiceConversation
      key={storageKey}
      storageKey={storageKey}
      story={params.get('story')}
      briefing={params.get('briefing')}
    />
  )
}

function VoiceConversation({
  storageKey,
  story,
  briefing,
}: {
  storageKey: string
  story: string | null
  briefing: string | null
}) {
  const health = useApi<Health>('/health')
  const useAgent = health.data?.conversation_provider === 'elevenagents'
  const agent = useElevenAgent(useAgent)
  const live = useRef<AgentConversation | null>(null)
  const [turns, setTurns] = useState<string[]>([])
  const [draft, setDraft] = useState('')
  const [phase, setPhase] = useState<VoicePhase>('idle')
  const [listening, setListening] = useState(false)
  const [error, setError] = useState('')
  const alive = useRef(true)
  const voice = useRef<RealtimeVoice | null>(null)
  const voiceOutput = useRef<AudioContext | null>(null)
  const microphone = useRef<LiveMicrophone | null>(null)
  const conversation = useRef<Promise<string> | null>(null)
  const audio = useRef<HTMLAudioElement>(null)
  const audioUrl = useRef('')
  const abort = useRef<AbortController | null>(null)

  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      voice.current?.close()
      void voiceOutput.current?.close()
      microphone.current?.stop()
      abort.current?.abort()
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current)
    }
  }, [])

  async function ensure() {
    if (!conversation.current) {
      const existing = sessionStorage.getItem(storageKey)
      conversation.current = existing
        ? Promise.resolve(existing)
        : api<Conversation>('/conversations', 'POST', {
            story_id: story,
            briefing_id: briefing,
          }).then((c) => {
            sessionStorage.setItem(storageKey, c.id)
            return c.id
          })
    }
    try {
      return await conversation.current
    } catch (e) {
      conversation.current = null
      throw e
    }
  }
  async function connection() {
    if (voice.current?.ready) return voice.current
    const id = await ensure()
    if (!alive.current) throw new DOMException('Aborted', 'AbortError')
    voice.current?.close()
    return (voice.current = new RealtimeVoice(
      id,
      {
        phase: (p) => {
          if (alive.current) setPhase(p)
        },
        microphone: (value) => {
          if (alive.current) setListening(value)
        },
        interrupt: () => {
          audio.current?.pause()
          abort.current?.abort()
        },
        story: () => undefined,
        action: () => {},
        finished: () => {},
        failed: (message) => {
          if (alive.current) {
            setError(message)
            setPhase('idle')
          }
        },
      },
      voiceOutput.current || undefined,
    ))
  }
  async function recordedAnswer(input: string | Blob) {
    abort.current?.abort()
    const controller = (abort.current = new AbortController())
    audio.current?.pause()
    setPhase('thinking')
    try {
      const cid = await ensure()
      const data = typeof input === 'string' ? { text: input } : new FormData()
      if (data instanceof FormData && input instanceof Blob)
        data.set(
          'file',
          input,
          input.type.includes('mp4') ? 'question.m4a' : 'question.webm',
        )
      const message = await api<Message>(
        `/conversations/${cid}/${typeof input === 'string' ? 'messages' : 'audio'}`,
        'POST',
        data,
        controller.signal,
      )
      const response = await request(
        `/conversations/${cid}/messages/${message.id}/audio`,
        'GET',
        undefined,
        controller.signal,
      )
      const blob = await response.blob()
      if (!alive.current || controller.signal.aborted) return
      if (audioUrl.current) URL.revokeObjectURL(audioUrl.current)
      audioUrl.current = URL.createObjectURL(blob)
      audio.current!.src = audioUrl.current
      await audio.current!.play()
    } catch (e) {
      if (alive.current && !controller.signal.aborted) {
        setError(
          e instanceof Error
            ? e.message
            : 'Spoken answer unavailable. Please try again.',
        )
        setPhase('idle')
      }
    }
  }
  async function send(text: string) {
    if (!useAgent) voiceOutput.current = unlockVoiceAudio(voiceOutput.current)
    setError('')
    setDraft('')
    try {
      if (useAgent) {
        if (live.current) live.current.sendUserMessage(text)
        else {
          const id = await ensure()
          const reply = await api<Message>(`/conversations/${id}/messages`, 'POST', { text })
          if (alive.current) setTurns((items) => [...items.slice(-48), text, reply.text])
        }
      } else if (health.data?.realtime_voice) await (await connection()).sendText(text)
      else await recordedAnswer(text)
    } catch (e) {
      if (alive.current) {
        setError(e instanceof Error ? e.message : 'Voice connection failed.')
        setPhase('idle')
      }
    }
  }
  async function toggleMicrophone() {
    if (!useAgent) voiceOutput.current = unlockVoiceAudio(voiceOutput.current)
    setError('')
    if (useAgent) {
      if (agent.status !== 'disconnected') {
        live.current = null
        void agent.stop()
        setListening(false)
        setPhase('idle')
        return
      }
      abort.current?.abort()
      audio.current?.pause()
      setPhase('connecting')
      const session = await agent.start(
        { story_id: story || undefined, briefing_id: briefing || undefined },
        {
          onMessage: ({ message }) => setTurns((items) => [...items.slice(-49), message]),
          onModeChange: ({ mode }) => setPhase(mode === 'speaking' ? 'speaking' : 'listening'),
          onDisconnect: () => { live.current = null; setListening(false); setPhase('idle') },
          onError: (message) => { setError(message); setPhase('idle') },
        },
      )
      if (session) {
        live.current = session
        setListening(true)
        setPhase('listening')
      }
      return
    }
    if (listening) {
      microphone.current?.stop()
      microphone.current = null
      await voice.current?.setMicrophone(false)
      setListening(false)
      return
    }
    setPhase('connecting')
    try {
      if (health.data?.realtime_voice)
        await (await connection()).setMicrophone(true)
      else {
        const mic = new LiveMicrophone(
          () => {
            audio.current?.pause()
            abort.current?.abort()
            setPhase('listening')
          },
          (blob) => void recordedAnswer(blob),
          (message) => {
            setError(message)
            setListening(false)
            microphone.current = null
          },
        )
        microphone.current = mic
        await mic.start()
        if (alive.current) {
          setListening(true)
          setPhase('listening')
        }
      }
    } catch (e) {
      voice.current?.close()
      voice.current = null
      microphone.current?.stop()
      microphone.current = null
      setListening(false)
      setPhase('idle')
      setError(e instanceof Error ? e.message : 'Microphone access failed.')
    }
  }
  function restart() {
    live.current = null
    void agent.stop()
    setTurns([])
    voice.current?.close()
    voice.current = null
    microphone.current?.stop()
    microphone.current = null
    abort.current?.abort()
    audio.current?.pause()
    conversation.current = null
    sessionStorage.removeItem(storageKey)
    setPhase('idle')
    setListening(false)
    setDraft('')
    setError('')
  }
  const busy = phase === 'thinking' || phase === 'connecting'
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">VOICE ASSISTANT</div>
        <h1>Ask Sourcera</h1>
        <p>A conversation, out loud.</p>
      </header>
      <Card className="voice-conversation">
        <div className="section-heading">
          <h2>
            {story
              ? 'About this story'
              : briefing
                ? 'About this briefing'
                : 'Your news companion'}
          </h2>
          <Button variant="quiet" onClick={restart}>
            <Plus size={16} /> New chat
          </Button>
        </div>
        <div className={'voice-orb ' + phase} aria-hidden="true">
          {busy ? (
            <LoaderCircle size={38} className="spin" strokeWidth={1} />
          ) : (
            <AudioLines size={46} strokeWidth={1} />
          )}
        </div>
        <p className="voice-conversation-status" role="status">
          {phase === 'connecting'
            ? 'Connecting voice…'
            : phase === 'thinking'
              ? 'Thinking…'
              : phase === 'speaking'
                ? 'Speaking'
                : listening
                  ? 'Listening · ask a question'
                  : 'Turn on the mic, or choose what to hear.'}
        </p>
        <div className="voice-conversation-controls">
          <Button
            type="button"
            variant={listening ? 'outline' : 'primary'}
            aria-label={
              useAgent ? (listening ? 'End voice session' : 'Start voice session') : (listening ? 'Turn microphone off' : 'Turn microphone on')
            }
            aria-pressed={listening}
            disabled={phase === 'connecting' || !health.data}
            onClick={() => void toggleMicrophone()}
          >
            {listening ? <Mic size={17} /> : <MicOff size={17} />}{' '}
            {listening ? 'Mic on' : 'Start talking'}
          </Button>
          <Button
            type="button"
            variant="quiet"
            disabled={busy}
            onClick={() => void send('More news')}
          >
            More news
          </Button>
        </div>
        <details className="voice-text-input">
          <summary>Type a question</summary>
          <form
            className="composer"
            onSubmit={(e) => {
              e.preventDefault()
              if (draft.trim() && !busy) void send(draft.trim())
            }}
          >
            <input
              aria-label="Your question"
              placeholder="Ask about your news…"
              maxLength={2000}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <button
              className="send"
              aria-label="Send question"
              disabled={busy || !draft.trim()}
            >
              <Send size={17} />
            </button>
          </form>
        </details>
        {useAgent && <p className="muted">Voice chat sends microphone audio and news context to ElevenLabs.</p>}
        {turns.length > 0 && (
          <section aria-label="Conversation transcript" aria-live="polite">
            {turns.map((turn, index) => <p key={index}>{turn}</p>)}
          </section>
        )}
        <audio
          ref={audio}
          onPlay={() => setPhase('speaking')}
          onEnded={() => setPhase(listening ? 'listening' : 'idle')}
        />
        <ErrorNote error={error || health.error} />
      </Card>
    </>
  )
}
