import { useEffect, useRef, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { AudioLines, Mic, MicOff, Plus, Send, Volume2 } from 'lucide-react'
import { api, request, queryClient } from '../../api/client'
import type { Conversation, Message, User } from '../../api/types'
import {
  Button,
  Card,
  ErrorNote,
  Loading,
  SourceCitation,
} from '../../components/UI'
export function ChatMessage({
  message: m,
  onSpeak,
  busy,
}: {
  message: Message
  onSpeak: () => void
  busy: boolean
}) {
  return (
    <article className={'chat-message ' + m.role}>
      <div className="chat-speaker">
        {m.role === 'user' ? (
          'You'
        ) : (
          <>
            <AudioLines size={15} /> Sourcera
          </>
        )}
      </div>
      <p>{m.text}</p>
      {m.action?.response_provider === 'source_search' && typeof m.action?.fallback_reason === 'string' && (
        <small>The AI answer was unavailable. Showing source search results.</small>
      )}
      {m.citations?.length > 0 && (
        <details>
          <summary>View evidence ({m.citations.length})</summary>
          {m.citations.map((c, i) => (
            <SourceCitation key={i} citation={c} />
          ))}
        </details>
      )}
      {m.role !== 'user' && (
        <div className="chat-actions">
          {m.action?.type === 'CHANGE_PREFERENCES' && (
            <Link className="text-link" to="/settings">
              Open settings
            </Link>
          )}
          <button className="text-link" disabled={busy} onClick={onSpeak}>
            <Volume2 size={15} />
            Listen to answer
          </button>
          {m.briefing_id && (
            <Link className="text-link" to={'/briefings/' + m.briefing_id}>
              Open briefing
            </Link>
          )}
          {m.story_id && (
            <Link className="text-link" to={'/stories/' + m.story_id}>
              Open story
            </Link>
          )}
        </div>
      )}
    </article>
  )
}
export function Assistant({ user }: { user: User }) {
  const [params] = useSearchParams()
  const key =
    'sourcera.conversation.' +
    user.id +
    '.' +
    (params.get('story') || params.get('briefing') || 'general')
  return (
    <ChatSession
      key={key}
      storageKey={key}
      story={params.get('story')}
      briefing={params.get('briefing')}
    />
  )
}
function ChatSession({
  storageKey,
  story,
  briefing,
}: {
  storageKey: string
  story: string | null
  briefing: string | null
}) {
  const [id, setId] = useState(() => sessionStorage.getItem(storageKey) || ''),
    [draft, setDraft] = useState(''),
    [error, setError] = useState(''),
    [recording, setRecording] = useState(false),
    [audioUrl, setAudioUrl] = useState(''),
    [speaking, setSpeaking] = useState(false)
  const recorder = useRef<MediaRecorder | null>(null),
    stream = useRef<MediaStream | null>(null),
    alive = useRef(true),
    spoken = useRef<HTMLAudioElement>(null)
  const q = useQuery({
    queryKey: ['conversation', id],
    enabled: !!id,
    queryFn: ({ signal }) =>
      api<Conversation>('/conversations/' + id, 'GET', undefined, signal),
  })
  const ensure = async () => {
    if (id) return id
    const v = await api<Conversation>('/conversations', 'POST', {
      briefing_id: briefing,
      story_id: story,
    })
    sessionStorage.setItem(storageKey, v.id)
    setId(v.id)
    return v.id
  }
  const send = useMutation({
    mutationFn: async (content: string | Blob) => {
      const cid = await ensure()
      if (typeof content === 'string')
        await api<Message>('/conversations/' + cid + '/messages', 'POST', {
          text: content,
        })
      else {
        const data = new FormData()
        data.set(
          'file',
          content,
          'question.' + (content.type.includes('mp4') ? 'mp4' : 'webm')
        )
        await api<Message>('/conversations/' + cid + '/audio', 'POST', data)
      }
      return api<Conversation>('/conversations/' + cid)
    },
    onSuccess: (conv) => {
      setDraft('')
      queryClient.setQueryData(['conversation', conv.id], conv)
      const action = conv.messages.at(-1)?.action?.type
      if (action === 'STOP_PLAYBACK') spoken.current?.pause()
      if (action === 'CHANGE_VOICE')
        queryClient.invalidateQueries({ queryKey: ['/users/me/preferences'] })
    },
  })
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
      if (recorder.current?.state === 'recording') {
        recorder.current.onstop = null
        recorder.current.stop()
      }
      stream.current?.getTracks().forEach((t) => t.stop())
    }
  }, [])
  useEffect(
    () => () => {
      if (audioUrl) URL.revokeObjectURL(audioUrl)
    },
    [audioUrl]
  )
  async function mic() {
    setError('')
    if (recorder.current?.state === 'recording') {
      recorder.current.stop()
      return
    }
    try {
      if (
        !navigator.mediaDevices?.getUserMedia ||
        typeof MediaRecorder === 'undefined'
      )
        throw Error(
          'Microphone recording requires a supported browser on localhost or HTTPS.'
        )
      const media = await navigator.mediaDevices.getUserMedia({ audio: true })
      if (!alive.current) {
        media.getTracks().forEach((t) => t.stop())
        return
      }
      stream.current = media
      const r = new MediaRecorder(media)
      recorder.current = r
      const chunks: BlobPart[] = []
      r.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data)
      }
      r.onstop = () => {
        media.getTracks().forEach((t) => t.stop())
        if (!alive.current) return
        setRecording(false)
        if (chunks.length) send.mutate(new Blob(chunks, { type: r.mimeType }))
      }
      r.start()
      setRecording(true)
    } catch (e) {
      stream.current?.getTracks().forEach((t) => t.stop())
      setError(e instanceof Error ? e.message : 'Microphone unavailable.')
    }
  }
  async function speak(m: Message) {
    setError('')
    setSpeaking(true)
    try {
      const r = await request(
        '/conversations/' + id + '/messages/' + m.id + '/audio'
      )
      const blob = await r.blob()
      if (alive.current) {
        setAudioUrl(URL.createObjectURL(blob))
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Audio unavailable.')
    } finally {
      if (alive.current) setSpeaking(false)
    }
  }
  function restart() {
    sessionStorage.removeItem(storageKey)
    setId('')
    setAudioUrl('')
    setDraft('')
    setError('')
    send.reset()
  }
  const busy = send.isPending || recording
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">VOICE ASSISTANT</div>
        <h1>Ask Sourcera</h1>
        <p>Explore the reporting behind your news, by text or voice.</p>
      </header>
      <Card className="chat">
        <div className="section-heading">
          <h2>
            {story
              ? 'Story discussion'
              : briefing
                ? 'Briefing discussion'
                : 'Conversation'}
          </h2>
          <Button variant="quiet" disabled={busy} onClick={restart}>
            <Plus size={16} />
            New chat
          </Button>
        </div>
        {story && (
          <Link className="text-link" to={'/stories/' + story}>
            View current story
          </Link>
        )}
        {briefing && (
          <Link className="text-link" to={'/briefings/' + briefing}>
            View current briefing
          </Link>
        )}
        {q.isFetching && !q.data && <Loading />}
        {!q.data?.messages.length && (
          <div className="assistant-intro">
            <span className="round-icon">
              <AudioLines size={25} />
            </span>
            <h3>What would you like to hear?</h3>
            <div className="chips">
              {(story || briefing
                ? ['What do other sources say?', 'Give me more details.', 'More news']
                : [
                    "Tell me today's news.",
                    'What happened this week?',
                    'Tell me about AI.',
                  ]
              ).map((t) => (
                <button disabled={busy} key={t} onClick={() => send.mutate(t)}>
                  {t}
                </button>
              ))}
            </div>
          </div>
        )}
        {q.data?.messages.map((m) => (
          <ChatMessage
            key={m.id}
            message={m}
            busy={speaking}
            onSpeak={() => speak(m)}
          />
        ))}
        {audioUrl && (
          <div>
            <audio
              key={audioUrl}
              ref={spoken}
              src={audioUrl}
              controls
              autoPlay
            />
            <small className="muted">AI-generated narration</small>
          </div>
        )}
        {send.isPending && <Loading>Finding evidence…</Loading>}
        <ErrorNote error={send.error || q.error || error} />
        <form
          className="composer"
          onSubmit={(e) => {
            e.preventDefault()
            if (draft.trim() && !busy) send.mutate(draft.trim())
          }}
        >
          <input
            aria-label="Your question"
            placeholder="Ask about your news…"
            value={draft}
            maxLength={2000}
            onChange={(e) => setDraft(e.target.value)}
          />
          <button
            type="button"
            className={'icon ' + (recording ? 'recording' : '')}
            disabled={send.isPending}
            aria-label={recording ? 'Finish recording' : 'Record question'}
            onClick={mic}
          >
            {recording ? <MicOff size={20} /> : <Mic size={20} />}
          </button>
          <button
            type="submit"
            className="send"
            disabled={busy || !draft.trim()}
            aria-label="Send question"
          >
            <Send size={17} />
          </button>
        </form>
        {recording && (
          <p role="status" className="muted">
            Recording… Press the microphone again to send.
          </p>
        )}
      </Card>
    </>
  )
}
