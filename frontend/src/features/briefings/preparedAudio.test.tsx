import { afterEach, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { queryClient, setToken, useBriefingAudio } from '../../api/client'
function Player() {
  const audio = useBriefingAudio('prepared-edition')
  return <output>{audio.data?.url || 'loading'}</output>
}
afterEach(() => {
  queryClient.clear()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})
it('retains prepared audio across mounts and releases it on sign-out', async () => {
  const create = vi.fn().mockReturnValue('blob:prepared-recording')
  const revoke = vi.fn()
  vi.stubGlobal(
    'URL',
    Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }),
  )
  const fetcher = vi
    .spyOn(globalThis, 'fetch')
    .mockResolvedValue(
      new Response('audio', { headers: { 'Content-Type': 'audio/wav' } }),
    )
  const first = render(
    <QueryClientProvider client={queryClient}>
      <Player />
    </QueryClientProvider>,
  )
  await screen.findByText('blob:prepared-recording')
  first.unmount()
  expect(revoke).not.toHaveBeenCalled()
  const second = render(
    <QueryClientProvider client={queryClient}>
      <Player />
    </QueryClientProvider>,
  )
  expect(screen.getByText('blob:prepared-recording')).toBeVisible()
  expect(fetcher).toHaveBeenCalledOnce()
  expect(create).toHaveBeenCalledOnce()
  second.unmount()
  act(() => setToken(null))
  expect(revoke).toHaveBeenCalledExactlyOnceWith('blob:prepared-recording')
})
