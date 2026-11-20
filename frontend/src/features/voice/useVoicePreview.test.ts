import { act, cleanup, renderHook, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { queryClient, request } from '../../api/client'
import { PLAYBACK_START, useVoicePreview } from './useVoicePreview'

vi.mock('../../api/client', async importOriginal => ({
  ...await importOriginal<typeof import('../../api/client')>(), request: vi.fn(),
}))
afterEach(() => { cleanup(); queryClient.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

function audio() {
  const nodes: any[] = []
  const resume = vi.fn().mockResolvedValue(undefined)
  vi.stubGlobal('AudioContext', class {
    state = 'running'
    sampleRate = 24000
    destination = {}
    resume = resume
    close = vi.fn().mockResolvedValue(undefined)
    createBuffer = () => ({ length: 1 })
    decodeAudioData = vi.fn().mockResolvedValue({ length: 24000 })
    createBufferSource() {
      const node = { buffer: null, connect: vi.fn(), disconnect: vi.fn(), start: vi.fn(), stop: vi.fn(), onended: null }
      nodes.push(node)
      return node
    }
  })
  return { nodes, resume }
}

it('unlocks audio during the click, ignores stale loads and stops previews for podcast playback', async () => {
  const { nodes, resume } = audio()
  let finish!: (response: Response) => void
  vi.mocked(request).mockImplementationOnce(() => new Promise(resolve => { finish = resolve }))
    .mockResolvedValueOnce(new Response('second-voice'))
  const { result } = renderHook(useVoicePreview)
  act(() => result.current.play('professional', 'openai', 'en'))
  expect(resume).toHaveBeenCalledOnce()
  expect(nodes[0].start).toHaveBeenCalledOnce()
  await waitFor(() => expect(request).toHaveBeenCalledOnce())
  act(() => result.current.play('energetic', 'elevenlabs', 'en'))
  await waitFor(() => expect(result.current.loading).toBe(false))
  expect(result.current.id).toBe('energetic')
  await act(async () => finish(new Response('late-first-voice')))
  const audible = nodes.filter(node => node.buffer?.length > 1)
  expect(audible).toHaveLength(1)
  expect(audible[0].start).toHaveBeenCalledOnce()
  act(() => window.dispatchEvent(new Event(PLAYBACK_START)))
  expect(audible[0].stop).toHaveBeenCalledOnce()
  expect(result.current.id).toBe('')
})

it('reuses preset audio and fetches custom samples again after a possible voice change', async () => {
  audio()
  vi.mocked(request).mockImplementation(async () => new Response('sample'))
  const { result, unmount } = renderHook(useVoicePreview)
  for (const id of ['jarvis', 'jarvis', 'custom', 'custom']) {
    act(() => result.current.play(id, 'elevenlabs', 'en'))
    await waitFor(() => expect(result.current.loading).toBe(false))
  }
  expect(request).toHaveBeenCalledTimes(3)
  expect(request).toHaveBeenLastCalledWith('/voices/custom/preview', 'POST', { engine: 'elevenlabs', language: 'en' }, undefined)
  unmount()
})
