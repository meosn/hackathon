import { StrictMode, useEffect } from 'react'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { api, queryClient, useApi } from '../../api/client'
import type { Preferences } from '../../api/types'
import { HomeVoiceGate } from './HomeVoiceGate'

let stored: Preferences
let mounts: string[]
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {
  status, headers: { 'Content-Type': 'application/json' },
})
function AudioPreparation() {
  const prefs = useApi<Preferences>('/users/me/preferences')
  useEffect(() => { mounts.push(prefs.data!.voice_engine) }, [])
  return <>
    <p>Prepared with {prefs.data!.voice_engine}</p>
    <button onClick={async () => {
      const data = await api<Preferences>('/users/me/preferences', 'PATCH', { voice_engine: 'openai' })
      queryClient.setQueryData(['/users/me/preferences'], data)
    }}>Choose OpenAI</button>
  </>
}
function show() {
  return render(<StrictMode><QueryClientProvider client={queryClient}>
    <HomeVoiceGate><AudioPreparation /></HomeVoiceGate>
  </QueryClientProvider></StrictMode>)
}
beforeEach(() => {
  queryClient.clear()
  stored = { voice_engine: 'openai', voice_profile_id: 'professional' } as Preferences
  mounts = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (_, options) => {
    if (options?.method === 'PATCH') stored = { ...stored, ...JSON.parse(String(options.body)) }
    return json(stored)
  })
})
afterEach(() => { queryClient.clear(); vi.restoreAllMocks() })

it('saves ElevenLabs before mounting any audio preparation for a saved OpenAI account', async () => {
  let release!: () => void
  const saved = new Promise<void>(resolve => { release = resolve })
  vi.mocked(fetch).mockImplementation(async (_, options) => {
    if (options?.method === 'PATCH') {
      await saved
      stored = { ...stored, ...JSON.parse(String(options.body)) }
    }
    return json(stored)
  })
  show()
  await waitFor(() => expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(true))
  expect(mounts).toEqual([])
  expect(screen.queryByText('Prepared with openai')).not.toBeInTheDocument()
  release()
  await screen.findByText('Prepared with elevenlabs')
  expect(mounts.every(engine => engine === 'elevenlabs')).toBe(true)
  expect(vi.mocked(fetch).mock.calls.filter(([, options]) => options?.method === 'PATCH')).toHaveLength(1)
})

it('keeps the listener’s manual choice during this visit and resets it on the next home entry', async () => {
  const first = show()
  await screen.findByText('Prepared with elevenlabs')
  fireEvent.click(screen.getByRole('button', { name: 'Choose OpenAI' }))
  await screen.findByText('Prepared with openai')
  expect(stored.voice_engine).toBe('openai')
  first.unmount()
  show()
  await screen.findByText('Prepared with elevenlabs')
  expect(stored.voice_engine).toBe('elevenlabs')
})

it('opens an existing ElevenLabs preference without writing it again', async () => {
  stored.voice_engine = 'elevenlabs'
  show()
  await screen.findByText('Prepared with elevenlabs')
  expect(vi.mocked(fetch).mock.calls.some(([, options]) => options?.method === 'PATCH')).toBe(false)
})

it('keeps OpenAI preparation unmounted if saving fails and allows retry', async () => {
  let fail = true
  vi.mocked(fetch).mockImplementation(async (_, options) => {
    if (options?.method === 'PATCH') {
      if (fail) return json({ detail: 'Could not save voice' }, 503)
      stored.voice_engine = 'elevenlabs'
    }
    return json(stored)
  })
  show()
  await screen.findByRole('alert')
  expect(mounts).toEqual([])
  fail = false
  fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
  await screen.findByText('Prepared with elevenlabs')
})
