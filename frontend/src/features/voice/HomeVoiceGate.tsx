import { useEffect, useRef, useState, type ReactNode } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, queryClient, useApi } from '../../api/client'
import type { Preferences } from '../../api/types'
import { ErrorNote, Loading } from '../../components/UI'

/** Select the home default before mounting anything that prepares audio. */
export function HomeVoiceGate({ children }: { children: ReactNode }) {
  const prefs = useApi<Preferences>('/users/me/preferences')
  const attempted = useRef(false)
  const [ready, setReady] = useState(false)
  const { mutate, error, isPending } = useMutation({
    mutationKey: ['voice-preferences'],
    mutationFn: () => api<Preferences>('/users/me/preferences', 'PATCH', { voice_engine: 'elevenlabs' }),
    onSuccess: data => {
      queryClient.setQueryData(['/users/me/preferences'], data)
      setReady(true)
    },
  })

  useEffect(() => {
    if (!prefs.data || attempted.current) return
    attempted.current = true
    if (prefs.data.voice_engine === 'elevenlabs') setReady(true)
    else mutate()
  }, [prefs.data, mutate])

  // Do not reapply the default when the listener switches engines during
  // this visit. A new home mount starts with ElevenLabs again.
  if (ready) return children

  const failure = prefs.error || error
  return <main id="main" className="music-main">
    {failure ? <>
      <ErrorNote error={failure} />
      <button type="button" className="btn outline" disabled={isPending}
        onClick={() => prefs.data ? mutate() : void prefs.refetch()}>Retry</button>
    </> : <Loading>Opening ElevenLabs Realtime…</Loading>}
  </main>
}
