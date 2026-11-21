import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import { CustomVoiceSettings } from './CustomVoice'
import { api, ApiError, useApi } from '../../api/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../../api/client', async original => ({
  ...await original<typeof import('../../api/client')>(), api: vi.fn(), useApi: vi.fn(),
}))
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.clearAllMocks() })
const state = { name: 'Custom', persona: '', saved: false, active: false, can_upload: true, can_create: true, sample_uploaded: false }

it('shows only name and file, creates in one action and retains input after a failed upload', async () => {
  vi.mocked(useApi).mockReturnValue({ data: state } as ReturnType<typeof useApi>)
  let attempts = 0
  vi.mocked(api).mockImplementation(async (path, method, data) => {
    if (path === '/users/me/custom-voice' && method === 'POST') {
      attempts++
      expect((data as FormData).get('name')).toBe('My host')
      expect((data as FormData).get('consent')).toBe('true')
      if (attempts === 1) throw new ApiError('Request failed (502)', 502)
      return { ...state, name: 'My host', saved: true, active: true }
    }
    return {}
  })
  const savePreferences = vi.fn(event => event.preventDefault())
  render(<QueryClientProvider client={new QueryClient()}><form onSubmit={savePreferences}><CustomVoiceSettings /></form></QueryClientProvider>)
  expect(document.querySelectorAll('form')).toHaveLength(1)
  expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  expect(screen.queryByText('Character name & delivery')).not.toBeInTheDocument()
  fireEvent.change(screen.getByRole('textbox', { name: 'Character name' }), { target: { value: 'My host' } })
  fireEvent.change(screen.getByLabelText('Voice recording'), { target: { files: [new File(['recording'], 'voice.m4a', { type: 'audio/mp4' })] } })
  fireEvent.click(screen.getByRole('button', { name: 'Create character' }))
  await screen.findByText(/Your name and recording are kept/)
  expect(screen.getByRole('textbox', { name: 'Character name' })).toHaveValue('My host')
  expect(screen.getByText('voice.m4a')).toBeVisible()
  fireEvent.click(screen.getByRole('button', { name: 'Create character' }))
  await waitFor(() => expect(attempts).toBe(2))
  expect(savePreferences).not.toHaveBeenCalled()
})
