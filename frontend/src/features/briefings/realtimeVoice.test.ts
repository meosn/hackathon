import { afterEach, expect, it, vi } from 'vitest'
import { RealtimeVoice } from './realtimeVoice'
import { api, request } from '../../api/client'
vi.mock('../../api/client', () => ({ api: vi.fn(), request: vi.fn() }))
const speechMock = vi.hoisted(() => ({
  connect: vi.fn().mockResolvedValue(undefined),
  append: vi.fn(),
  finish: vi.fn(),
  cancel: vi.fn(),
  close: vi.fn(),
  prepare: vi.fn(),
  callbacks: null as any,
  setStoryOrder: vi.fn(),
  resume: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('./elevenSpeech', () => ({
  ElevenSpeech: class {
    constructor(_id: string, _context: unknown, callbacks: unknown) {
      speechMock.callbacks = callbacks
    }
    connect = speechMock.connect
    append = speechMock.append
    finish = speechMock.finish
    cancel = speechMock.cancel
    close = speechMock.close
    prepare = speechMock.prepare
    setStoryOrder = speechMock.setStoryOrder
    resume = speechMock.resume
  },
}))
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
  vi.useRealTimers()
})

function setup() {
  const sent: Record<string, any>[] = []
  const stop = vi.fn(),
    replaceTrack = vi.fn().mockResolvedValue(undefined),
    pause = vi.fn(),
    play = vi.fn().mockResolvedValue(undefined)
  const channel = {
    readyState: 'connecting',
    onopen: null as null | (() => void),
    onclose: null as null | (() => void),
    onmessage: null as null | ((e: { data: string }) => void),
    send: (data: string) => sent.push(JSON.parse(data)),
    close: vi.fn(),
  }
  class Peer {
    ontrack = null
    onconnectionstatechange = null
    connectionState = 'new'
    createDataChannel() {
      return channel
    }
    addTransceiver() {
      return { sender: { replaceTrack } }
    }
    createOffer() {
      return Promise.resolve({ sdp: 'test-offer' })
    }
    setLocalDescription() {
      return Promise.resolve()
    }
    setRemoteDescription() {
      channel.readyState = 'open'
      channel.onopen?.()
      return Promise.resolve()
    }
    close = vi.fn()
  }
  vi.stubGlobal('RTCPeerConnection', Peer)
  vi.stubGlobal(
    'Audio',
    class {
      autoplay = false
      srcObject = null
      setAttribute = vi.fn()
      play = play
      pause = pause
    },
  )
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: {
      getUserMedia: vi.fn().mockResolvedValue({
        getTracks: () => [{ stop }],
        getAudioTracks: () => [{ stop }],
      }),
    },
  })
  vi.mocked(request).mockResolvedValue(new Response('answer-sdp'))
  const callbacks = {
    phase: vi.fn(),
    interrupt: vi.fn(),
    microphone: vi.fn(),
    story: () => 'playing-story',
    action: vi.fn(),
    finished: vi.fn(),
    failed: vi.fn(),
  }
  const voice = new RealtimeVoice('conversation', callbacks)
  const event = (data: Record<string, unknown>) =>
    channel.onmessage?.({ data: JSON.stringify(data) })
  return { voice, callbacks, event, sent, stop, replaceTrack, pause, play }
}

it('releases input while a streamed spoken answer continues and never sends cancellation on mute', async () => {
  const { voice, callbacks, event, sent, stop, replaceTrack, pause } = setup()
  await voice.setMicrophone(true)
  event({ type: 'response.created' })
  event({ type: 'output_audio_buffer.started' })
  sent.length = 0
  await voice.setMicrophone(false)
  expect(stop).toHaveBeenCalledOnce()
  expect(replaceTrack).toHaveBeenLastCalledWith(null)
  expect(callbacks.microphone).toHaveBeenLastCalledWith(false)
  expect(pause).not.toHaveBeenCalled()
  expect(sent.map((e) => e.type)).not.toContain('response.cancel')
  expect(sent.map((e) => e.type)).not.toContain('output_audio_buffer.clear')
  event({ type: 'output_audio_buffer.stopped' })
  expect(callbacks.finished).toHaveBeenCalledOnce()
  voice.close()
})

it('fetches more news directly without a model tool round trip or microphone permission', async () => {
  const { voice, event, sent, callbacks } = setup()
  vi.mocked(api).mockResolvedValue({
    text: 'Verified next three stories.',
    action: { type: 'GET_MORE_NEWS' },
    story_id: 'next-story',
    context: {
      stories: [
        { story_id: 'next-story', evidence: ['More verified context'] },
      ],
    },
  })
  await voice.moreNews()
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  expect(api).toHaveBeenCalledExactlyOnceWith(
    '/conversations/conversation/realtime-evidence',
    'POST',
    { question: 'More news', decision: { intent: 'GET_MORE_NEWS' } },
    expect.any(AbortSignal),
  )
  expect(callbacks.action).toHaveBeenCalledOnce()
  expect(
    sent.some((e) =>
      e.item?.content?.[0]?.text?.includes('Verified next three stories.'),
    ),
  ).toBe(true)
  expect(
    sent.some((e) =>
      e.item?.content?.[0]?.text?.includes('More verified context'),
    ),
  ).toBe(true)
  expect(
    sent.filter((e) => e.type === 'response.create').at(-1)?.response
      .tool_choice,
  ).toBe('none')
  event({ type: 'output_audio_buffer.started' })
  expect(callbacks.phase).toHaveBeenLastCalledWith('speaking')
  voice.close()
})

it('supplies current playback context before a direct spoken answer without an evidence request', async () => {
  const { voice, event, sent, callbacks } = setup()
  await voice.setMicrophone(true)
  event({ type: 'input_audio_buffer.speech_started' })
  expect(
    sent.some(
      (e) =>
        e.item?.role === 'system' &&
        e.item.content[0].text.includes('playing-story'),
    ),
  ).toBe(true)
  event({ type: 'input_audio_buffer.speech_stopped' })
  event({ type: 'response.created' })
  event({ type: 'output_audio_buffer.started' })
  expect(api).not.toHaveBeenCalled()
  expect(callbacks.phase).toHaveBeenLastCalledWith('speaking')
  voice.close()
})

it('warms the verified prefix silently without changing playback or conversation state', async () => {
  const { voice, event, sent, callbacks } = setup()
  await voice.connect()
  callbacks.phase.mockClear()
  voice.warmup()
  voice.warmup()
  const warmups = sent.filter(
    (e) => e.response?.metadata?.purpose === 'cache_warmup',
  )
  expect(warmups).toHaveLength(1)
  expect(warmups[0].response.conversation).toBe('none')
  expect(warmups[0].response.output_modalities).toEqual(['text'])
  event({
    type: 'response.created',
    response: { metadata: { purpose: 'cache_warmup' } },
  })
  event({
    type: 'response.done',
    response: { status: 'incomplete', metadata: { purpose: 'cache_warmup' } },
  })
  expect(callbacks.phase).not.toHaveBeenCalled()
  expect(callbacks.interrupt).not.toHaveBeenCalled()
  expect(callbacks.failed).not.toHaveBeenCalled()
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  voice.close()
})

it('streams GPT text to ElevenLabs and rejects late text from an interrupted answer', async () => {
  const { voice, event, sent, callbacks, play } = setup()
  vi.stubGlobal(
    'AudioContext',
    class {
      resume = vi.fn().mockResolvedValue(undefined)
      close = vi.fn().mockResolvedValue(undefined)
    },
  )
  vi.mocked(request).mockResolvedValue(
    new Response('answer-sdp', {
      headers: { 'X-Speech-Output': 'elevenlabs' },
    }),
  )
  await voice.connect()
  await voice.sendText('A question')
  expect(
    sent.filter((e) => e.type === 'response.create').at(-1)?.response
      .output_modalities,
  ).toEqual(['text'])
  event({ type: 'response.created', response: { id: 'answer-1' } })
  event({
    type: 'response.output_text.delta',
    response_id: 'answer-1',
    delta: 'Streaming words ',
  })
  expect(speechMock.append).toHaveBeenLastCalledWith(
    'answer-1',
    'Streaming words ',
  )
  speechMock.callbacks.started()
  expect(callbacks.phase).toHaveBeenLastCalledWith('speaking')
  speechMock.callbacks.blocked()
  expect(callbacks.phase).toHaveBeenLastCalledWith('blocked')
  await voice.resumeOutput()
  expect(speechMock.resume).toHaveBeenCalledOnce()
  expect(play).not.toHaveBeenCalled()
  const cancellations = speechMock.cancel.mock.calls.length
  await voice.setMicrophone(false)
  expect(speechMock.cancel).toHaveBeenCalledTimes(cancellations)
  event({ type: 'input_audio_buffer.speech_started' })
  event({
    type: 'response.output_text.delta',
    response_id: 'answer-1',
    delta: 'Must not be spoken',
  })
  expect(speechMock.append).toHaveBeenCalledTimes(1)
  event({ type: 'response.created', response: { id: 'answer-2' } })
  event({
    type: 'response.output_text.delta',
    response_id: 'answer-2',
    delta: 'New answer',
  })
  expect(speechMock.append).toHaveBeenLastCalledWith('answer-2', 'New answer')
  event({ type: 'response.output_text.done', response_id: 'answer-2' })
  expect(speechMock.finish).toHaveBeenLastCalledWith('answer-2')
  voice.close()
})
