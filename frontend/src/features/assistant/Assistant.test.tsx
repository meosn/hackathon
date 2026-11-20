import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { User } from '../../api/types'
import { useElevenAgent } from '../voice/useElevenAgent'
import { Assistant } from './Assistant'

vi.mock('../voice/useElevenAgent')

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

describe('assistant live voice', () => {
  it('passes story and briefing context to ElevenAgents and displays its turns', async () => {
    const start = vi.fn<ReturnType<typeof useElevenAgent>['start']>(
      async (_scope, callbacks) => {
        callbacks?.onMessage?.({
          source: 'user',
          role: 'user',
          event_id: 1,
          message: 'What happened?',
        })
        callbacks?.onMessage?.({
          source: 'ai',
          role: 'agent',
          event_id: 2,
          message: 'Here is the report.',
        })
        return null
      }
    )
    vi.mocked(useElevenAgent).mockReturnValue({
      start,
      stop: vi.fn(),
      status: 'disconnected',
    })
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({ conversation_provider: 'elevenagents' }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter initialEntries={['/assistant?story=report&briefing=morning']}>
          <Assistant user={{ id: 'listener' } as User} />
        </MemoryRouter>
      </QueryClientProvider>
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Start voice session' }))
    expect(await screen.findByText('Here is the report.')).toBeVisible()
    expect(screen.getByText('What happened?')).toBeVisible()
    expect(start).toHaveBeenCalledWith(
      { story_id: 'report', briefing_id: 'morning' },
      expect.any(Object)
    )
    expect(fetcher).toHaveBeenCalledTimes(1)
  })

  it('reports a configured agent failure without recording through the offline provider', async () => {
    const start = vi.fn<ReturnType<typeof useElevenAgent>['start']>(
      async (_scope, callbacks) => {
        callbacks?.onError?.('Live voice unavailable.')
        return null
      }
    )
    vi.mocked(useElevenAgent).mockReturnValue({
      start,
      stop: vi.fn(),
      status: 'disconnected',
    })
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      Response.json({ conversation_provider: 'elevenagents' }),
    )
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter>
          <Assistant user={{ id: 'listener' } as User} />
        </MemoryRouter>
      </QueryClientProvider>
    )
    fireEvent.click(await screen.findByRole('button', { name: 'Start voice session' }))
    expect(await screen.findByText('Live voice unavailable.')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Record question' })).toBeNull()
    await waitFor(() => expect(fetcher).toHaveBeenCalledTimes(1))
  })
})
