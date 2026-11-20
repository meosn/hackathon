import { afterEach, expect, it, vi } from 'vitest'
import { ElevenSpeech } from './elevenSpeech'
import { api, queryClient } from '../../api/client'
vi.mock('../../api/client', () => ({
  api: vi.fn(),
  queryClient: { getQueryData: vi.fn() },
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})
function setup() {
  const sockets: FakeSocket[] = [],
    sources: any[] = [],
    buffers: Float32Array[] = []
  class FakeSocket {
    static OPEN = 1
    readyState = 0
    onopen: (() => void) | null = null
    onclose: (() => void) | null = null
    onerror: (() => void) | null = null
    onmessage: ((e: { data: string }) => void) | null = null
    sent: any[] = []
    constructor(public url: URL) {
      sockets.push(this)
    }
    send(s: string) {
      this.sent.push(JSON.parse(s))
    }
    close = vi.fn(() => {
      this.readyState = 3
      this.onclose?.()
    })
    open() {
      this.readyState = 1
      this.onopen?.()
    }
    receive(value: unknown) {
      this.onmessage?.({ data: JSON.stringify(value) })
    }
  }
  vi.stubGlobal('WebSocket', FakeSocket)
  const context = {
    currentTime: 1,
    destination: {},
    createBuffer: vi.fn((_channels: number, size: number, rate: number) => {
      const data = new Float32Array(size)
      buffers.push(data)
      return { duration: size / rate, getChannelData: () => data }
    }),
    createBufferSource: () => {
      const source = {
        buffer: null,
        start: vi.fn(),
        connect: vi.fn(),
        disconnect: vi.fn(),
        stop: vi.fn(),
        onended: null as (() => void) | null,
      }
      sources.push(source)
      return source
    },
  }
  const callbacks = { started: vi.fn(), finished: vi.fn(), failed: vi.fn() }
  vi.mocked(api).mockResolvedValue({
    token: 'ephemeral-only',
    voice_id: 'voice-a',
    voice_profile_id: 'professional',
    model_id: 'eleven_flash_v2_5',
    sample_rate: 24000,
  })
  vi.mocked(queryClient.getQueryData).mockReturnValue({
    voice_profile_id: 'professional',
  })
  const speech = new ElevenSpeech(
    'conversation',
    context as unknown as AudioContext,
    callbacks,
  )
  async function connect() {
    const pending = speech.connect()
    await vi.waitFor(() => expect(sockets.length).toBeGreaterThan(0))
    sockets.at(-1)!.open()
    await pending
    return sockets.at(-1)!
  }
  return { speech, sockets, sources, buffers, callbacks, connect }
}
const pcm = btoa(String.fromCharCode(0, 64, 0, 192))

it('plays PCM before the text ends and finishes only after the final audio drains', async () => {
  const { speech, sources, buffers, callbacks, connect } = setup(),
    socket = await connect()
  speech.append('reply', 'Привет, мир. ')
  await vi.waitFor(() =>
    expect(
      socket.sent.some(
        (e) => e.context_id === 'reply' && e.text === 'Привет, мир. ',
      ),
    ).toBe(true),
  )
  socket.receive({ contextId: 'reply', audio: pcm })
  expect(callbacks.started).toHaveBeenCalledOnce()
  expect(sources[0].start).toHaveBeenCalledOnce()
  expect([...buffers[0]]).toEqual([0.5, -0.5])
  socket.receive({ context_id: 'reply', is_final: true })
  sources[0].onended()
  expect(callbacks.finished).not.toHaveBeenCalled()
  speech.append('reply', 'Ещё новости. ')
  speech.finish('reply')
  socket.receive({ contextId: 'reply', audio: pcm, isFinal: true })
  expect(callbacks.finished).not.toHaveBeenCalled()
  sources[1].onended()
  expect(callbacks.finished).toHaveBeenCalledOnce()
  speech.close()
})

it('stops queued audio on interruption and ignores late chunks from the old answer', async () => {
  const { speech, sources, callbacks, connect } = setup(),
    socket = await connect()
  speech.append('old', 'The old answer. ')
  await vi.waitFor(() =>
    expect(socket.sent.some((e) => e.context_id === 'old')).toBe(true),
  )
  socket.receive({ context_id: 'old', audio: pcm })
  speech.cancel()
  expect(sources[0].stop).toHaveBeenCalledOnce()
  socket.receive({ context_id: 'old', audio: pcm, is_final: true })
  expect(sources).toHaveLength(1)
  expect(callbacks.finished).not.toHaveBeenCalled()
  speech.append('next', 'A new answer. ')
  await vi.waitFor(() =>
    expect(socket.sent.some((e) => e.context_id === 'next')).toBe(true),
  )
  socket.receive({ context_id: 'next', audio: pcm })
  expect(callbacks.started).toHaveBeenCalledTimes(2)
  speech.close()
})

it('uses a new one-use authorization when the selected narrator changes', async () => {
  const { speech, sockets, connect } = setup()
  await connect()
  speech.append('first', 'Hello. ')
  await vi.waitFor(() =>
    expect(sockets[0].sent.some((e) => e.context_id === 'first')).toBe(true),
  )
  speech.cancel()
  vi.mocked(queryClient.getQueryData).mockReturnValue({
    voice_profile_id: 'casual',
  })
  vi.mocked(api).mockResolvedValue({
    token: 'another-one-use-token',
    voice_id: 'voice-b',
    voice_profile_id: 'casual',
    model_id: 'eleven_flash_v2_5',
    sample_rate: 24000,
  })
  speech.append('second', 'A different voice. ')
  await vi.waitFor(() => expect(sockets).toHaveLength(2))
  sockets[1].open()
  await vi.waitFor(() =>
    expect(sockets[1].sent.some((e) => e.context_id === 'second')).toBe(true),
  )
  expect(sockets[0].close).toHaveBeenCalled()
  expect(String(sockets[1].url)).toContain('/voice-b/multi-stream-input')
  expect(String(sockets[1].url)).toContain(
    'single_use_token=another-one-use-token',
  )
  expect(api).toHaveBeenCalledTimes(2)
  speech.close()
})
