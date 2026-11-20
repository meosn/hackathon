import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { api, queryClient, useApi } from '../../api/client'
import { Button, ErrorNote } from '../../components/UI'

export const customVoicePath = '/users/me/custom-voice'
export type CustomVoiceState = {
  saved: boolean
  active: boolean
  can_upload: boolean
  can_create: boolean
  sample_uploaded: boolean
}

export function setCustomVoice(active: boolean) {
  return api<CustomVoiceState>(customVoicePath, 'PATCH', { active })
}

export function CustomVoiceSettings() {
  const voice = useApi<CustomVoiceState>(customVoicePath)
  const [file, setFile] = useState<File | null>(null)
  const [consent, setConsent] = useState(false)
  const section = useRef<HTMLElement>(null)
  useEffect(() => {
    if (window.location.hash === '#custom-voice') section.current?.scrollIntoView()
  }, [])
  const update = useMutation({
    mutationFn: async (action: 'upload' | 'toggle' | 'create') => {
      if (action === 'toggle') return setCustomVoice(!voice.data?.active)
      if (action === 'create') return api<CustomVoiceState>(customVoicePath + '/create', 'POST')
      if (!file || !consent) throw new Error('Select an audio sample and confirm permission.')
      const data = new FormData()
      data.set('file', file)
      data.set('consent', 'true')
      return api<CustomVoiceState>(customVoicePath, 'POST', data)
    },
    onSuccess: (state) => {
      queryClient.setQueryData([customVoicePath], state)
      setFile(null)
      setConsent(false)
    },
  })

  return (
    <section ref={section} id="custom-voice" className="preference-block">
      <h3>Custom live voice</h3>
      {voice.data?.saved ? (
        <>
          <p role="status">{voice.data.active ? 'Custom voice selected for your next live conversation.' : 'Custom voice saved.'}</p>
          <Button type="button" disabled={update.isPending} onClick={() => update.mutate('toggle')}>
            {voice.data.active ? 'Use the default live voice' : 'Use Custom'}
          </Button>
        </>
      ) : voice.data?.can_upload ? (
        <div className="form-stack">
          {voice.data.sample_uploaded && (
            <p role="status">Audio sample uploaded to your profile.</p>
          )}
          <label className="field">
            Voice sample (30–60 seconds)
            <input key={Number(voice.data.sample_uploaded)} type="file" accept="audio/*,.m4a,.webm" disabled={update.isPending}
              onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
          </label>
          <p className="preference-hint">
            Upload up to 10 MiB. Creating a live voice sends the sample to ElevenLabs.
          </p>
          <label className="check">
            <input type="checkbox" checked={consent} onChange={(event) => setConsent(event.target.checked)} />
            I have permission to clone the voice in this recording.
          </label>
          <Button type="button" disabled={!file || !consent || update.isPending}
            onClick={() => update.mutate('upload')}>
            {update.isPending ? 'Working…' : voice.data.sample_uploaded ? 'Replace audio' : 'Upload audio'}
          </Button>
          {voice.data.sample_uploaded && voice.data.can_create && (
            <Button type="button" disabled={update.isPending} onClick={() => update.mutate('create')}>
              Create custom voice from saved audio
            </Button>
          )}
          {!voice.data.can_create && (
            <p className="preference-hint">
              Creating the live voice requires a personal account and a configured ElevenLabs agent.
            </p>
          )}
        </div>
      ) : voice.isPending ? (
        <p role="status">Loading custom voice…</p>
      ) : !voice.error ? (
        <p className="preference-hint">Custom voices require a personal account and a configured ElevenLabs agent.</p>
      ) : null}
      <ErrorNote error={update.error || voice.error} />
    </section>
  )
}
