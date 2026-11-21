import { useEffect, useRef, useState } from 'react'
import { useMutation } from '@tanstack/react-query'
import { UploadCloud, Check } from 'lucide-react'
import { api, ApiError, queryClient, useApi } from '../../api/client'
import { Button, ErrorNote } from '../../components/UI'

export const customVoicePath = '/users/me/custom-voice'
export type CustomVoiceState = {
  name: string; persona: string; saved: boolean; active: boolean;
  can_upload: boolean; can_create: boolean; sample_uploaded: boolean; revision?: string
}
export function setCustomVoice(active: boolean) {
  return api<CustomVoiceState>(customVoicePath, 'PATCH', { active })
}

export function CustomVoiceSettings() {
  const voice = useApi<CustomVoiceState>(customVoicePath)
  const [file, setFile] = useState<File | null>(null)
  const [name, setName] = useState('')
  const initialized = useRef(false)
  const input = useRef<HTMLInputElement>(null)
  const section = useRef<HTMLElement>(null)
  useEffect(() => {
    if (voice.data && !initialized.current) {
      initialized.current = true
      setName(voice.data.saved || voice.data.sample_uploaded ? voice.data.name : '')
    }
  }, [voice.data])
  useEffect(() => {
    if (window.location.hash === '#custom-voice') section.current?.scrollIntoView()
  }, [])
  const update = useMutation({
    mutationFn: async () => {
      if (!name.trim()) throw Error('Give your character a name.')
      try {
        if (file) {
          if (file.size > 25 * 1024 * 1024) throw Error('Choose an audio file smaller than 25 MB.')
          const data = new FormData()
          data.set('file', file); data.set('name', name.trim()); data.set('consent', 'true')
          return await api<CustomVoiceState>(customVoicePath, 'POST', data)
        }
        await api(customVoicePath, 'PATCH', { name: name.trim(), ...(voice.data?.saved && !voice.data.sample_uploaded ? { active: true } : {}) })
        return voice.data?.sample_uploaded
          ? await api<CustomVoiceState>(customVoicePath + '/create', 'POST')
          : await api<CustomVoiceState>(customVoicePath)
      } catch (error) {
        if (error instanceof ApiError && /^Request failed/.test(error.message)) throw Error('Could not finish creating the voice. Your name and recording are kept. Please try again.')
        throw error
      }
    },
    onSuccess: state => {
      queryClient.setQueryData([customVoicePath], state)
      setName(state.name); setFile(null)
      if (input.current) input.current.value = ''
      void queryClient.invalidateQueries({ queryKey: ['/users/me/preferences'] })
      void queryClient.invalidateQueries({ queryKey: ['prepared-editions'] })
      void api('/briefings/prepare', 'POST').catch(() => {})
    },
    onError: () => { void queryClient.invalidateQueries({ queryKey: [customVoicePath] }) },
  })
  return <section ref={section} id="custom-voice" className="preference-block custom-character">
    <h3>Your character</h3>
    <form onSubmit={event => { event.preventDefault(); update.mutate() }}>
      <label className="field">Character name
        <input aria-label="Character name" placeholder="Give your narrator a name" value={name} maxLength={80} required
          onChange={event => setName(event.target.value)} disabled={update.isPending} />
      </label>
      <label className={'character-upload' + (file ? ' has-file' : '')}>
        <UploadCloud size={24} strokeWidth={1.5} />
        <span><strong>{file?.name || (voice.data?.sample_uploaded ? 'Recording saved — ready to create' : voice.data?.saved ? 'Choose a new recording to change the voice' : 'Choose an audio recording')}</strong>
        <small>M4A, MP3 or WAV · up to 25 MB · 1–2 minutes works best</small></span>
        <input ref={input} aria-label="Voice recording" type="file" accept="audio/*,.m4a,.webm" disabled={update.isPending}
          onChange={event => setFile(event.target.files?.[0] || null)} />
      </label>
      <p className="preference-hint">Use a recording you have permission to clone.</p>
      <Button type="submit" disabled={update.isPending || !name.trim() || (!file && !voice.data?.saved && !voice.data?.sample_uploaded)}>
        {update.isPending ? 'Creating your character…' : voice.data?.sample_uploaded && !file ? 'Create from saved recording' : voice.data?.saved ? 'Save character' : 'Create character'}
      </Button>
      {update.isSuccess && voice.data?.saved && <p className="character-ready" role="status"><Check size={15} /> Ready — selected for your briefings and voice chat.</p>}
      <ErrorNote error={update.error || voice.error} />
    </form>
  </section>
}
