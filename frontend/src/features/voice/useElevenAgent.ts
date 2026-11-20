import { useCallback, useEffect, useRef, useState } from 'react'
import type { VoiceConversation, Callbacks, ClientToolsConfig } from '@elevenlabs/client'
import { ApiError, api } from '../../api/client'

export type AgentConversation = VoiceConversation
export type AgentScope = {
  briefing_id?: string
  story_id?: string
  playback_seconds?: number
}
type AgentStatus = 'disconnected' | 'connecting' | 'connected'
type SessionDetails = { signed_url: string; context: string }
type AgentCallbacks = Pick<
  Callbacks,
  'onMessage' | 'onModeChange' | 'onDisconnect' | 'onVadScore' | 'onInterruption'
> &
  Partial<ClientToolsConfig> & { onError?: (message: string) => void }
type PendingSession = {
  control: AbortController
  conversation?: AgentConversation
  result?: Promise<AgentConversation | null>
}

async function closeConversation(conversation?: AgentConversation) {
  if (!conversation) return
  try {
    conversation.setMicMuted(true)
    conversation.setVolume({ volume: 0 })
  } catch {
    // The connection may have ended while its setup was being cancelled.
  }
  try {
    await conversation.endSession()
  } catch {
    // The SDK may already have released its audio devices.
  }
}

export function useElevenAgent(enabled = false) {
  const [status, setStatus] = useState<AgentStatus>('disconnected')
  const pending = useRef<PendingSession | null>(null)

  const stop = useCallback(() => {
    const entry = pending.current
    pending.current = null
    entry?.control.abort()
    setStatus('disconnected')
    return closeConversation(entry?.conversation)
  }, [])

  useEffect(() => () => {
    const entry = pending.current
    pending.current = null
    entry?.control.abort()
    void closeConversation(entry?.conversation)
  }, [])

  useEffect(() => {
    // The SDK registers an iOS gesture listener for unlocking playback on import.
    if (enabled) void import('@elevenlabs/client').catch(() => undefined)
  }, [enabled])

  function start(
    scope: AgentScope | (() => AgentScope),
    callbacks: AgentCallbacks = {},
  ): Promise<AgentConversation | null> {
    if (pending.current?.result) return pending.current.result
    const entry: PendingSession = { control: new AbortController() }
    pending.current = entry
    setStatus('connecting')
    const valid = () => pending.current === entry && !entry.control.signal.aborted
    const getScope = () => (typeof scope === 'function' ? scope() : scope)

    async function refreshContext(moreNews = false) {
      if (!valid()) return 'The Sourcera session has ended.'
      const scope = getScope()
      try {
        const fresh = await api<{ context: string }>(
          '/agent-context', 'POST', moreNews ? { ...scope, more_news: true } : scope, entry.control.signal,
        )
        return fresh.context
      } catch {
        return 'The requested Sourcera context is unavailable. Say that you could not retrieve it.'
      }
    }

    async function connect() {
      try {
        const [session, { VoiceConversation }] = await Promise.all([
          api<SessionDetails>('/agent-session', 'POST', getScope(), entry.control.signal),
          import('@elevenlabs/client'),
        ])
        if (!valid()) return null
        const conversation = await VoiceConversation.startSession({
          signedUrl: session.signed_url,
          connectionType: 'websocket',
          textOnly: false,
          dynamicVariables: { sourcera_context: session.context },
          clientTools: {
            ...callbacks.clientTools,
            get_sourcera_context: () => refreshContext(),
            get_more_sourcera_news: () => refreshContext(true),
          },
          onConversationCreated: (created) => {
            if (created.type === 'voice' && valid()) entry.conversation = created
          },
          onMessage: (message) => { if (valid()) callbacks.onMessage?.(message) },
          onModeChange: (mode) => { if (valid()) callbacks.onModeChange?.(mode) },
          onVadScore: (score) => { if (valid()) callbacks.onVadScore?.(score) },
          onInterruption: (event) => { if (valid()) callbacks.onInterruption?.(event) },
          onError: () => {
            if (valid()) callbacks.onError?.('ElevenLabs reported a voice session error.')
          },
          onDisconnect: (details) => {
            if (!valid()) return
            pending.current = null
            entry.control.abort()
            setStatus('disconnected')
            callbacks.onDisconnect?.(details)
            if (details.reason === 'error') callbacks.onError?.('The ElevenLabs connection was lost.')
          },
        })
        if (!valid()) {
          await closeConversation(conversation)
          return null
        }
        entry.conversation = conversation
        setStatus('connected')
        return conversation
      } catch (error) {
        if (!valid()) return null
        void stop()
        callbacks.onError?.(
          error instanceof ApiError
            ? error.message
            : error instanceof DOMException && error.name === 'NotAllowedError'
              ? 'Allow microphone access to start the voice conversation.'
              : 'Unable to connect to ElevenLabs. Check your microphone and try again.',
        )
        return null
      }
    }

    return (entry.result = connect())
  }

  return { start, stop, status }
}
