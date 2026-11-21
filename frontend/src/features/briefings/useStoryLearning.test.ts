import { act, renderHook } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { useStoryLearning } from './useStoryLearning'
import { api } from '../../api/client'
import type { BriefingDetail } from '../../api/types'
vi.mock('../../api/client', () => ({ api: vi.fn().mockResolvedValue(undefined) }))
afterEach(() => vi.clearAllMocks())
it('learns from meaningful listening once, while ignoring seeks and paused playback', () => {
  const edition = { id: 'episode', segments: [{ story_id: 'politics', start_seconds: 0, end_seconds: 40 }] } as BriefingDetail
  const { rerender } = renderHook(({ position, playing }) => useStoryLearning(edition, position, playing), { initialProps: { position: 0, playing: true } })
  act(() => rerender({ position: 35, playing: true }))
  act(() => rerender({ position: 0, playing: true }))
  expect(api).not.toHaveBeenCalled()
  for (let p = .5; p <= 26; p += .5) act(() => rerender({ position: p, playing: true }))
  expect(api).toHaveBeenCalledExactlyOnceWith('/listening-history/politics', 'PUT')
  act(() => rerender({ position: 38, playing: false }))
  expect(api).toHaveBeenCalledTimes(1)
})
