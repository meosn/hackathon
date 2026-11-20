import { afterEach, expect, it, vi } from 'vitest'
import { RealtimeVoice } from './realtimeVoice'
import { api, request } from '../../api/client'
vi.mock('../../api/client', () => ({ api: vi.fn(), request: vi.fn() }))
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
      getUserMedia: vi
        .fn()
        .mockResolvedValue({
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

it('requests more news without microphone permission and speaks the grounded tool result', async () => {
  const { voice, event, sent, callbacks } = setup()
  vi.mocked(api).mockResolvedValue({
    text: 'Verified next three stories.',
    action: { type: 'GET_MORE_NEWS' },
    story_id: 'next-story',
  })
  await voice.moreNews()
  expect(navigator.mediaDevices.getUserMedia).not.toHaveBeenCalled()
  event({ type: 'response.created' })
  event({
    type: 'response.function_call_arguments.done',
    call_id: 'call-1',
    name: 'news_evidence',
    arguments: JSON.stringify({
      question: 'More news',
      decision: { intent: 'GET_MORE_NEWS' },
    }),
  })
  await vi.waitFor(() => expect(api).toHaveBeenCalledOnce())
  await vi.waitFor(() => expect(callbacks.action).toHaveBeenCalledOnce())
  expect(
    sent.some(
      (e) =>
        e.item?.type === 'function_call_output' &&
        JSON.parse(e.item.output).evidence === 'Verified next three stories.',
    ),
  ).toBe(true)
  const before = sent.filter((e) => e.type === 'response.create').length
  event({ type: 'response.done', response: { status: 'completed' } })
  expect(sent.filter((e) => e.type === 'response.create')).toHaveLength(
    before + 1,
  )
  event({ type: 'output_audio_buffer.started' })
  expect(callbacks.phase).toHaveBeenLastCalledWith('speaking')
  voice.close()
})
