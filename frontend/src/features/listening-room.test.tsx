import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import type { ReactNode } from 'react'
import { Auth } from './auth/Auth'
import { SourceCitation } from '../components/UI'
import { activeSegment, BriefingForm } from './briefings/Briefings'
import { Assistant } from './assistant/Assistant'
import { Explore } from './news/News'
import type { Segment } from '../api/types'
import { clockTime } from '../api/client'
const wrap = (node: ReactNode) =>
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  )
const json = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  })
beforeEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockImplementation(
    () => null,
  )
})
describe('source traceability and timing', () => {
  it('shows the quote and original link for a real report', () => {
    render(
      <SourceCitation
        citation={{
          source: 'Dispatch',
          url: 'https://news.example.org/report',
          article_id: 'a',
          excerpt: 'The launch took place on Tuesday.',
        }}
      />,
    )
    expect(screen.getByText('The launch took place on Tuesday.')).toBeVisible()
    expect(
      screen.getByRole('link', { name: 'Original article' }),
    ).toHaveAttribute('href', 'https://news.example.org/report')
  })
  it('labels a synthetic source and omits a fabricated destination', () => {
    render(
      <SourceCitation
        citation={{
          source: 'Demo',
          url: 'https://demo.example/report',
          article_id: 'a',
          excerpt: 'A synthetic example.',
          is_synthetic: true,
        }}
      />,
    )
    expect(screen.getByText('Synthetic source')).toBeVisible()
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
  })
  it('selects the next segment exactly on the timing boundary', () => {
    const segments = [
      { start_seconds: 0, end_seconds: 2 },
      { start_seconds: 2, end_seconds: 7 },
    ] as Segment[]
    expect(activeSegment(segments, 1.9)).toBe(segments[0])
    expect(activeSegment(segments, 2)).toBe(segments[1])
    expect(activeSegment(segments, 7)).toBeUndefined()
    expect(clockTime(82.4)).toEqual('1:22')
  })
})
describe('listener workflows', () => {
  it('offers personal sign-in without demo profiles or automatic guest access', async () => {
    const fetcher = vi.spyOn(globalThis, 'fetch').mockResolvedValue(json({ access_token: 'personal-test' }))
    wrap(<Auth />)
    expect(screen.queryByRole('button', { name: 'Technology enthusiast' })).not.toBeInTheDocument()
    expect(screen.queryByText('Demo profiles')).not.toBeInTheDocument()
    expect(fetcher).not.toHaveBeenCalled()
    fireEvent.change(screen.getByLabelText('Email'), { target: { value: 'listener@example.test' } })
    fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'personal-password' } })
    fireEvent.submit(screen.getByLabelText('Email').closest('form')!)
    await waitFor(() => expect(sessionStorage.getItem('sourcera.session')).toBe('personal-test'))
    expect(fetcher.mock.calls[0][0]).toBe('/api/v1/auth/login')
  })
  it('sends filters and sort to the server', async () => {
    const fetcher = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (path) =>
        json(
          String(path).endsWith('topics')
            ? [{ name: 'finance', count: 1 }]
            : { items: [], next_cursor: null },
        ),
      )
    wrap(<Explore />)
    await screen.findByRole('option', { name: 'Finance' })
    fireEvent.change(screen.getByLabelText('Topic'), {
      target: { value: 'finance' },
    })
    fireEvent.change(screen.getByLabelText('Sort stories'), {
      target: { value: 'importance' },
    })
    fireEvent.change(screen.getByRole('searchbox'), {
      target: { value: 'emissions' },
    })
    await waitFor(() =>
      expect(
        fetcher.mock.calls.some(([p]) =>
          [
            'topic=finance',
            'search=emissions',
            'sort=importance',
            'date_from=',
          ].every((part) => String(p).includes(part)),
        ),
      ).toBe(true),
    )
  })
  it('submits duration, voice and language from the current profile', async () => {
    const fetcher = vi
      .spyOn(globalThis, 'fetch')
      .mockImplementation(async (p, opt) => {
        if (opt?.method === 'POST') return json({ briefing_id: 'b' })
        if (String(p).endsWith('preferences'))
          return json({
            language: 'de',
            duration_minutes: 6,
            voice_profile_id: 'professional',
          })
        if (String(p).endsWith('voices'))
          return json([
            { id: 'professional', name: 'Professional', description: '' },
          ])
        return json([])
      })
    wrap(<BriefingForm />)
    fireEvent.click(
      await screen.findByRole('button', { name: 'Generate audio briefing' }),
    )
    await waitFor(() =>
      expect(
        fetcher.mock.calls.find(
          ([p, o]) => p === '/api/v1/briefings' && o?.method === 'POST',
        )?.[1]?.body,
      ).toEqual(
        JSON.stringify({
          period: 'week',
          topic: null,
          duration_minutes: 6,
          language: 'de',
          voice_profile_id: 'professional',
          selected_story_ids: [],
        }),
      ),
    )
  })
  it('keeps the assistant voice-only and offers an explicit question input', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      json({ realtime_voice: false }),
    )
    wrap(<Assistant user={{ id: 'listener' } as never} />)
    expect(screen.getByText('A conversation, out loud.')).toBeVisible()
    expect(
      screen.getByRole('button', { name: 'Turn microphone on' }),
    ).toBeVisible()
    expect(screen.getByLabelText('Your question')).not.toBeVisible()
    fireEvent.click(screen.getByText('Type a question'))
    expect(screen.getByRole('textbox', { name: 'Your question' })).toBeVisible()
    expect(screen.queryByText('Listen to answer')).not.toBeInTheDocument()
  })
})
