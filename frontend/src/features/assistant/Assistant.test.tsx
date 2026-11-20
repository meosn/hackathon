import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import type { User } from '../../api/types'
import { Assistant } from './Assistant'

const voice = vi.hoisted(() => ({ callbacks: null as any, setMicrophone: vi.fn(), close: vi.fn(), create: vi.fn() }))
vi.mock('../voice/voiceChoice', () => ({
  useVoiceChoice: () => ({ engine: 'elevenlabs', ready: true, signature: 'elevenlabs:energetic' }),
  createVoiceConnection: (...args: any[]) => { voice.create(...args); voice.callbacks = args[2]; return { setMicrophone: voice.setMicrophone, close: voice.close, disposed: false } },
}))
vi.mock('../briefings/realtimeVoice', async importOriginal => ({
  ...await importOriginal<object>(), unlockVoiceAudio: () => ({ close: vi.fn() }),
}))
beforeEach(() => {
  vi.spyOn(HTMLMediaElement.prototype, 'pause').mockImplementation(() => {})
  vi.spyOn(globalThis, 'fetch').mockImplementation(async path => Response.json(
    String(path).endsWith('/health') ? { realtime_voice: true } : { id: 'conversation' },
  ))
})
afterEach(() => { vi.restoreAllMocks(); vi.clearAllMocks(); sessionStorage.clear() })
function show() {
  render(<QueryClientProvider client={new QueryClient()}>
    <MemoryRouter initialEntries={['/assistant?story=report&briefing=morning']}>
      <Assistant user={{ id: 'listener' } as User} />
    </MemoryRouter>
  </QueryClientProvider>)
}

it('uses the listener’s selected provider and keeps the spoken reply playing when the microphone is muted', async () => {
  voice.setMicrophone.mockImplementation(async enabled => { voice.callbacks.microphone(enabled); if (enabled) voice.callbacks.phase('speaking') })
  show()
  const microphone = await screen.findByRole('button', { name: 'Turn microphone on' })
  await waitFor(() => expect(microphone).toBeEnabled())
  fireEvent.click(microphone)
  expect(await screen.findByText('Speaking')).toBeVisible()
  expect(voice.create.mock.calls[0].slice(0, 2)).toEqual(['elevenlabs', 'conversation'])
  const conversationRequest = vi.mocked(fetch).mock.calls.find(([path]) => String(path).endsWith('/conversations'))!
  expect(JSON.parse(conversationRequest[1]!.body as string)).toEqual({ story_id: 'report', briefing_id: 'morning' })
  fireEvent.click(screen.getByRole('button', { name: 'Turn microphone off' }))
  await waitFor(() => expect(voice.setMicrophone).toHaveBeenLastCalledWith(false))
  expect(screen.getByText('Speaking')).toBeVisible()
  expect(screen.queryByRole('region', { name: 'Conversation transcript' })).toBeNull()
  expect(voice.close).not.toHaveBeenCalled()
})

it('reports a selected live provider failure without silently switching to recording', async () => {
  voice.setMicrophone.mockRejectedValueOnce(Error('Live voice unavailable.'))
  show()
  const microphone = await screen.findByRole('button', { name: 'Turn microphone on' })
  await waitFor(() => expect(microphone).toBeEnabled())
  fireEvent.click(microphone)
  expect(await screen.findByText('Live voice unavailable.')).toBeVisible()
  expect(vi.mocked(fetch).mock.calls.some(([path]) => String(path).endsWith('/audio'))).toBe(false)
})
