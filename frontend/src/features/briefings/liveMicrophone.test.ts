import { afterEach, expect, it, vi } from 'vitest'
import { LiveMicrophone } from './liveMicrophone'
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})
it('interrupts on sustained speech, submits after silence and releases the microphone', async () => {
  vi.useFakeTimers()
  const stop = vi.fn()
  const media = { getTracks: () => [{ stop }] }
  Object.defineProperty(navigator, 'mediaDevices', {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue(media) },
  })
  let amplitude = 0
  class Context {
    resume = vi.fn().mockResolvedValue(undefined)
    close = vi.fn().mockResolvedValue(undefined)
    createMediaStreamSource() {
      return { connect: vi.fn() }
    }
    createAnalyser() {
      return {
        fftSize: 0,
        getFloatTimeDomainData: (samples: Float32Array) =>
          samples.fill(amplitude),
      }
    }
  }
  class Recorder {
    static isTypeSupported() {
      return true
    }
    state = 'inactive'
    mimeType = 'audio/webm'
    onstop: (() => void) | null = null
    ondataavailable: ((event: { data: Blob }) => void) | null = null
    start() {
      this.state = 'recording'
    }
    stop() {
      this.state = 'inactive'
      this.ondataavailable?.({ data: new Blob(['speech']) })
      this.onstop?.()
    }
  }
  vi.stubGlobal('AudioContext', Context)
  vi.stubGlobal('MediaRecorder', Recorder)
  const interrupt = vi.fn(),
    utterance = vi.fn(),
    failed = vi.fn()
  const mic = new LiveMicrophone(interrupt, utterance, failed)
  await mic.start()
  await vi.advanceTimersByTimeAsync(400)
  expect(interrupt).not.toHaveBeenCalled()
  amplitude = 0.08
  await vi.advanceTimersByTimeAsync(400)
  expect(interrupt).toHaveBeenCalledOnce()
  amplitude = 0
  await vi.advanceTimersByTimeAsync(800)
  expect(utterance).toHaveBeenCalledOnce()
  expect(utterance.mock.calls[0][0]).toBeInstanceOf(Blob)
  amplitude = 0.08
  await vi.advanceTimersByTimeAsync(400)
  expect(interrupt).toHaveBeenCalledTimes(2)
  mic.stop()
  expect(stop).toHaveBeenCalledOnce()
  expect(failed).not.toHaveBeenCalled()
  await vi.advanceTimersByTimeAsync(1000)
  expect(utterance).toHaveBeenCalledOnce()
})
