import { act, renderHook, waitFor } from '@testing-library/react'
import type { PartialOptions } from '@elevenlabs/client'
import { afterEach, expect, it, vi } from 'vitest'
import { useElevenAgent } from './useElevenAgent'

const { startSession } = vi.hoisted(() => ({ startSession: vi.fn() }))
vi.mock('@elevenlabs/client', () => ({ VoiceConversation: { startSession } }))

function fakeConversation() {
  return {
    type: 'voice',
    setMicMuted: vi.fn(),
    setVolume: vi.fn(),
    endSession: vi.fn().mockResolvedValue(undefined),
  }
}

afterEach(() => {
  vi.restoreAllMocks()
  startSession.mockReset()
})

it('starts a signed voice WebSocket and refreshes episode context with the current playhead', async () => {
  let position = 12
  const conversation = fakeConversation()
  const fetcher = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(Response.json({
      signed_url: 'wss://api.elevenlabs.io/v1/convai/conversation?signature=mock',
      context: 'initial episode context',
    }))
    .mockResolvedValueOnce(Response.json({ context: 'new episode context' }))
    .mockResolvedValueOnce(Response.json({ context: 'other recent news' }))
  startSession.mockResolvedValue(conversation)
  const { result } = renderHook(() => useElevenAgent())

  await act(async () => {
    await result.current.start(() => ({
      briefing_id: 'edition-1', playback_seconds: position,
    }))
  })
  expect(result.current.status).toBe('connected')
  expect(fetcher).toHaveBeenNthCalledWith(1, '/api/v1/agent-session', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ briefing_id: 'edition-1', playback_seconds: 12 }),
  }))
  const options: PartialOptions = startSession.mock.calls[0][0]
  expect(options).toMatchObject({
    signedUrl: 'wss://api.elevenlabs.io/v1/convai/conversation?signature=mock',
    connectionType: 'websocket',
    textOnly: false,
    dynamicVariables: { sourcera_context: 'initial episode context' },
  })
  position = 75
  expect(await options.clientTools?.get_sourcera_context({ briefing_id: 'foreign' }))
    .toBe('new episode context')
  expect(fetcher).toHaveBeenNthCalledWith(2, '/api/v1/agent-context', expect.objectContaining({
    method: 'POST', body: JSON.stringify({ briefing_id: 'edition-1', playback_seconds: 75 }),
  }))
  expect(await options.clientTools?.get_more_sourcera_news({ story_id: 'foreign' }))
    .toBe('other recent news')
  expect(fetcher).toHaveBeenNthCalledWith(3, '/api/v1/agent-context', expect.objectContaining({
    method: 'POST', body: JSON.stringify({
      briefing_id: 'edition-1', playback_seconds: 75, more_news: true,
    }),
  }))
})

it('closes a late SDK connection instead of activating it after the user stops', async () => {
  const conversation = fakeConversation()
  vi.spyOn(globalThis, 'fetch').mockResolvedValueOnce(Response.json({
    signed_url: 'wss://api.elevenlabs.io/v1/convai/conversation?signature=mock',
    context: 'initial episode context',
  }))
  let finish!: (value: ReturnType<typeof fakeConversation>) => void
  startSession.mockReturnValue(new Promise((resolve) => { finish = resolve }))
  const { result } = renderHook(() => useElevenAgent())
  let connect: ReturnType<typeof result.current.start>
  act(() => { connect = result.current.start({ briefing_id: 'edition-1' }) })
  await waitFor(() => expect(startSession).toHaveBeenCalledOnce())
  await act(async () => { await result.current.stop() })
  await act(async () => {
    finish(conversation)
    expect(await connect).toBeNull()
  })

  expect(result.current.status).toBe('disconnected')
  expect(conversation.setMicMuted).toHaveBeenCalledWith(true)
  expect(conversation.endSession).toHaveBeenCalledOnce()
})
