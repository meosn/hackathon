import { afterEach, expect, it, vi } from 'vitest'
import { ElevenRealtime } from './elevenRealtime'
import { api } from '../../api/client'
vi.mock('../../api/client', () => ({ api: vi.fn() }))
const output = vi.hoisted(() => ({
  queuePcm: vi.fn(), cancel: vi.fn(), close: vi.fn(), resume: vi.fn(), setStoryOrder: vi.fn(), callbacks: null as any,
}))
vi.mock('./elevenSpeech', () => ({ ElevenSpeech: class {
  constructor(_id: string, _context: unknown, callbacks: unknown) { output.callbacks = callbacks }
  queuePcm = output.queuePcm
  cancel = output.cancel
  close = output.close
  resume = output.resume
  setStoryOrder = output.setStoryOrder
} }))
afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks(); vi.clearAllMocks() })

function setup() {
  const sockets: FakeSocket[] = []
  class FakeSocket {
    static OPEN = 1
    readyState = 0
    onopen: (() => void) | null = null
    onclose: (() => void) | null = null
    onmessage: ((event: { data: string }) => void) | null = null
    sent: any[] = []
    constructor(public url: string) { sockets.push(this) }
    send(text: string) { this.sent.push(JSON.parse(text)) }
    close = vi.fn()
    receive(value: unknown) { this.onmessage?.({ data: JSON.stringify(value) }) }
    open() { this.readyState = 1; this.onopen?.() }
  }
  vi.stubGlobal('WebSocket', FakeSocket)
  const stop = vi.fn()
  Object.defineProperty(navigator, 'mediaDevices', { configurable: true, value: {
    getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [{ stop }] }),
  } })
  const processors: any[] = []
  vi.stubGlobal('AudioWorkletNode', class {
    port = { onmessage: null }
    connect = vi.fn()
    disconnect = vi.fn()
    constructor() { processors.push(this) }
  })
  const context = { audioWorklet: { addModule: vi.fn().mockResolvedValue(undefined) }, resume: vi.fn().mockResolvedValue(undefined),
    createMediaStreamSource: vi.fn(() => ({ connect: vi.fn(), disconnect: vi.fn() })), destination: {} }
  const callbacks = { phase: vi.fn(), interrupt: vi.fn(), microphone: vi.fn(), story: () => undefined,
    action: vi.fn(), finished: vi.fn(), failed: vi.fn(), research: vi.fn() }
  vi.mocked(api).mockImplementation(async path => path === '/agent-session'
    ? { signed_url: 'wss://api.elevenlabs.io/v1/convai/conversation?conversation_signature=one-use', context: 'Verified evidence', voice_id: 'saved-character', persona: 'Energetic speaker', language: 'en' }
    : { text: 'Three verified next stories.', action: { type: 'GET_MORE_NEWS', story_ids: ['a', 'b', 'c'] } })
  const voice = new ElevenRealtime('conversation', callbacks, context as unknown as AudioContext)
  async function connect() {
    const promise = voice.connect()
    await vi.waitFor(() => expect(sockets).toHaveLength(1))
    const socket = sockets[0]
    socket.open()
    socket.receive({ type: 'conversation_initiation_metadata', conversation_initiation_metadata_event: { user_input_audio_format: 'pcm_16000', agent_output_audio_format: 'pcm_24000' } })
    await promise
    return socket
  }
  return { voice, callbacks, sockets, context, processors, stop, connect }
}

it('uses the stored character on a signed WebSocket and reads more news without microphone permission', async () => {
  const { voice, callbacks, connect } = setup(), socket = await connect()
  expect(socket.sent[0]).toMatchObject({ type: 'conversation_initiation_client_data',
    dynamic_variables: { sourcera_context: 'Verified evidence', sourcera_persona: 'Energetic speaker' },
    conversation_config_override: { tts: { voice_id: 'saved-character' } } })
  await voice.moreNews()
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  expect(socket.sent.at(-1).text).toContain('Three verified next stories.')
  socket.receive({ type: 'audio', audio_event: { event_id: 1, audio_base_64: 'AQACAA==' } })
  expect(output.queuePcm).toHaveBeenCalledWith('AQACAA==', 24000, undefined)
  expect(callbacks.phase).not.toHaveBeenCalledWith('speaking')
  output.callbacks.started()
  expect(callbacks.phase).toHaveBeenLastCalledWith('speaking')
  socket.receive({ type: 'ping', ping_event: { event_id: 9 } })
  expect(socket.sent.at(-1)).toEqual({ type: 'pong', event_id: 9 })
  voice.close()
})

it('streams PCM input and releases only the microphone on mute while output continues', async () => {
  const { voice, context, processors, stop, connect } = setup(), socket = await connect()
  await voice.setMicrophone(true)
  expect(context.audioWorklet.addModule).toHaveBeenCalledWith('/voice-input-worklet.js')
  processors[0].port.onmessage({ data: new Uint8Array([1, 0, 2, 0]).buffer })
  expect(socket.sent.at(-1)).toEqual({ user_audio_chunk: 'AQACAA==' })
  const cancellations = output.cancel.mock.calls.length
  await voice.setMicrophone(false)
  expect(stop).toHaveBeenCalledOnce()
  expect(processors[0].disconnect).toHaveBeenCalledOnce()
  expect(socket.close).not.toHaveBeenCalled()
  expect(output.cancel).toHaveBeenCalledTimes(cancellations)
  socket.receive({ type: 'audio', audio_event: { event_id: 1, audio_base_64: 'AQACAA==' } })
  expect(output.queuePcm).toHaveBeenCalledOnce()
  voice.close()
})

it('discards late interrupted audio and refreshes only its own conversation context', async () => {
  const { voice, callbacks, connect } = setup(), socket = await connect()
  socket.receive({ type: 'audio', audio_event: { event_id: 1, audio_base_64: 'AQACAA==' } })
  socket.receive({ type: 'interruption', interruption_event: { event_id: 3 } })
  socket.receive({ type: 'audio', audio_event: { event_id: 2, audio_base_64: 'OLD' } })
  socket.receive({ type: 'audio', audio_event: { event_id: 4, audio_base_64: 'NEW' } })
  expect(output.queuePcm).toHaveBeenCalledTimes(2)
  expect(callbacks.interrupt).toHaveBeenCalled()
  socket.receive({ type: 'client_tool_call', client_tool_call: { tool_name: 'get_sourcera_context', tool_call_id: 'call', parameters: { conversation_id: 'someone-else' } } })
  await vi.waitFor(() => expect(socket.sent.at(-1).type).toBe('client_tool_result'))
  expect(api).toHaveBeenLastCalledWith('/agent-context', 'POST', { conversation_id: 'conversation', story_id: undefined }, expect.any(AbortSignal))
  output.callbacks.blocked()
  expect(callbacks.phase).toHaveBeenLastCalledWith('blocked')
  await voice.resumeOutput()
  expect(output.resume).toHaveBeenCalledOnce()
  voice.close()
})

it('routes research consent and results through the authenticated conversation without changing stories', async () => {
  const { voice, callbacks, connect } = setup(), socket = await connect()
  const offered = { status: 'offered', query: 'Mars moons', answer: 'Offer to look it up.', sources: [] }
  vi.mocked(api).mockResolvedValueOnce(offered)
  socket.receive({ type: 'client_tool_call', client_tool_call: {
    tool_name: 'research_topic', tool_call_id: 'offer',
    parameters: { action: 'offer', query: 'Mars moons', conversation_id: 'someone-else' },
  } })
  await vi.waitFor(() => expect(callbacks.research).toHaveBeenCalledWith(offered))
  expect(api).toHaveBeenLastCalledWith('/conversations/conversation/research', 'POST',
    { action: 'offer', query: 'Mars moons' }, expect.any(AbortSignal))
  expect(socket.sent.at(-1)).toMatchObject({ type: 'client_tool_result', tool_call_id: 'offer', is_error: false })
  expect(callbacks.action).not.toHaveBeenCalled()
  const completed = { ...offered, status: 'completed', answer: 'Mars has two moons.', sources: [{ title: 'NASA', url: 'https://science.nasa.gov/mars/' }] }
  vi.mocked(api).mockResolvedValueOnce(completed)
  socket.receive({ type: 'client_tool_call', client_tool_call: {
    tool_name: 'research_topic', tool_call_id: 'search', parameters: { action: 'search' },
  } })
  await vi.waitFor(() => expect(callbacks.research).toHaveBeenCalledWith(completed))
  expect(api).toHaveBeenLastCalledWith('/conversations/conversation/research', 'POST', { action: 'search' }, expect.any(AbortSignal))
  expect(output.setStoryOrder).not.toHaveBeenCalled()
  voice.close()
})
