import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { expect, it } from 'vitest'

it('downsamples microphone audio to little-endian PCM in 20 ms frames without speaker feedback', () => {
  let Processor: any
  const frames: ArrayBuffer[] = []
  runInNewContext(readFileSync('public/voice-input-worklet.js', 'utf8'), {
    sampleRate: 48000,
    AudioWorkletProcessor: class { port = { postMessage: (frame: ArrayBuffer) => frames.push(frame) } },
    registerProcessor: (_name: string, constructor: any) => { Processor = constructor },
  })
  const input = new Processor({ processorOptions: { sampleRate: 16000 } })
  for (let i = 0; i < 8; i++) input.process([[new Float32Array(128).fill(.5)]])
  expect(frames).toHaveLength(1)
  expect(frames[0].byteLength).toBe(640)
  expect(new DataView(frames[0]).getInt16(0, true)).toBe(16384)
})
