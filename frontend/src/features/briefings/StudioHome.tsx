import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AudioLines, Check, Play, Plus, LoaderCircle, Volume2, Lock } from 'lucide-react'
import { api, clockTime, niceDate, queryClient, useApi } from '../../api/client'
import type { Health } from '../../api/client'
import type { Briefing, Preferences, User } from '../../api/types'
import { SpeakerAvatar } from '../../components/SpeakerAvatar'
import { ErrorNote } from '../../components/UI'
import { customVoicePath, setCustomVoice, type CustomVoiceState } from '../voice/CustomVoice'
import { DailySession } from './DailySession'
import './studio.css'
import { VoiceEnginePicker } from '../voice/VoiceEnginePicker'
import { useVoicePreview } from '../voice/useVoicePreview'
import { PremiumNotice } from '../voice/PremiumNotice'
import { usePreparedEditions } from './usePreparedEditions'

const hosts = [
  { id: 'professional', name: 'The Anchor' },
  { id: 'jarvis', name: 'Studio Assistant' },
  { id: 'energetic', name: 'Donald Trump' },
  { id: 'gangsta', name: 'CJ · GTA Gangsta' },
]
export function StudioHome({ user }: { user: User }) {
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])
  const custom = useApi<CustomVoiceState>(customVoicePath)
  const selectCustom = useMutation({
    mutationFn: setCustomVoice,
    onSuccess: (data) => {
      queryClient.setQueryData([customVoicePath], data)
      void queryClient.invalidateQueries({ queryKey: ['/users/me/preferences'] })
    },
  })
  const prefs = useApi<Preferences>('/users/me/preferences')
  const briefs = useApi<Briefing[]>('/briefings')
  const health = useApi<Health>('/health')
  const [selectedId, setSelectedId] = useState('')
  const [playRequest, setPlayRequest] = useState(0)
  const [premiumNotice, setPremiumNotice] = useState(false)
  const prepared = usePreparedEditions()
  const preview = useVoicePreview()
  const engine = useMutation({
    mutationFn: (voice_engine: string) => api<Preferences>('/users/me/preferences', 'PATCH', { voice_engine }),
    onSuccess: data => {
      queryClient.setQueryData(['/users/me/preferences'], data)
      void queryClient.invalidateQueries({ queryKey: [customVoicePath] })
    },
  })
  const save = useMutation({
    mutationKey: ['voice-preferences'],
    mutationFn: (voice_profile_id: string) =>
      api<Preferences>('/users/me/preferences', 'PATCH', {
        voice_profile_id,
        ...(voice_profile_id === 'energetic' ? { voice_engine: 'elevenlabs' } : {}),
      }),
    onMutate: async (voice_profile_id) => {
      await queryClient.cancelQueries({ queryKey: ['/users/me/preferences'] })
      const previous = queryClient.getQueryData<Preferences>([
        '/users/me/preferences',
      ])
      if (previous)
        queryClient.setQueryData(['/users/me/preferences'], {
          ...previous,
          voice_profile_id,
          ...(voice_profile_id === 'energetic' ? { voice_engine: 'elevenlabs' } : {}),
        })
      return { previous }
    },
    onError: (_error, _voice, context) => {
      if (context?.previous)
        queryClient.setQueryData(['/users/me/preferences'], context.previous)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['/users/me/preferences'], data)
    },
  })
  function selectEpisode(id: string) {
    setSelectedId(id)
    setPlayRequest((n) => n + 1)
    document
      .getElementById('main')
      ?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
  const episodes =
    briefs.data
      ?.filter(
        (b) =>
          b.status === 'completed' &&
          new Date(b.created_at).toDateString() !== new Date().toDateString(),
      )
      .slice(0, 4) || []
  const weekly = prepared.data?.weekly
  return (
    <>
      <main id="main" className="music-main">
        {premiumNotice && <PremiumNotice onClose={() => setPremiumNotice(false)} />}
        <DailySession selectedId={selectedId} playRequest={playRequest} />
        <section className="music-voices" aria-label="Choose your voice">
          <div className="music-section-heading">
            <h2>Your voice</h2>
            <Link to="/settings?section=audio">Change voice</Link>
          </div>
          <VoiceEnginePicker value={prefs.data?.voice_engine || 'openai'} disabled={engine.isPending || !prefs.data}
            onChange={value => engine.mutate(value)} />
          <ErrorNote error={engine.error} />
          <div className="music-hosts">
            {hosts.map((host) => (
              <button
                type="button"
                key={host.id}
                aria-pressed={!custom.data?.active && prefs.data?.voice_profile_id === host.id}
                className={'music-host' + (host.id === 'gangsta' && !user.is_premium ? ' locked' : '')}
                title={'Preview and select ' + host.name}
                disabled={save.isPending || selectCustom.isPending || !prefs.data}
                onClick={async () => {
                  if (host.id === 'gangsta' && !user.is_premium) { setPremiumNotice(true); return }
                  preview.play(host.id, host.id === 'energetic' ? 'elevenlabs' : prefs.data?.voice_engine || 'openai', prefs.data?.language || 'en')
                  if (custom.data?.active) {
                    try { await selectCustom.mutateAsync(false) } catch { return }
                  }
                  save.mutate(host.id)
                }}
              >
                <span className="portrait-wrap">
                  <SpeakerAvatar id={host.id} />
                  <span className={'voice-preview-indicator' + (preview.id === host.id || host.id === 'gangsta' && !user.is_premium ? ' active' : '')} aria-hidden="true">
                    {host.id === 'gangsta' && !user.is_premium ? <Lock size={24} /> : preview.id === host.id ? preview.loading ? <LoaderCircle className="spin" size={20} /> : <Volume2 size={20} /> : <Play size={18} fill="currentColor" />}
                  </span>
                  {!custom.data?.active && prefs.data?.voice_profile_id === host.id && (
                    <span className="voice-check">
                      <Check size={13} />
                    </span>
                  )}
                </span>
                <span>{host.name}</span>
              </button>
            ))}
            {custom.data?.saved && (
              <button type="button" className="music-host" aria-pressed={custom.data.active}
                disabled={selectCustom.isPending || save.isPending}
                title="Preview and select your custom voice"
                onClick={() => { preview.play('custom', 'elevenlabs', prefs.data?.language || 'en'); selectCustom.mutate(true) }}>
                <span className="portrait-wrap">
                  <span className="speaker-avatar custom-voice-icon" aria-hidden="true">C</span>
                  <span className={'voice-preview-indicator' + (preview.id === 'custom' ? ' active' : '')} aria-hidden="true">
                    {preview.id === 'custom' ? preview.loading ? <LoaderCircle className="spin" size={20} /> : <Volume2 size={20} /> : <Play size={18} fill="currentColor" />}
                  </span>
                  {custom.data.active && <span className="voice-check"><Check size={13} /></span>}
                </span>
                <span>{custom.data.name || 'Custom'}</span>
              </button>
            )}
            <Link to="/settings?section=audio#custom-voice" className="music-host">
              <span className="portrait-wrap">
                <span className="speaker-avatar custom-voice-icon" aria-hidden="true"><Plus size={28} /></span>
              </span>
              <span>Add voice</span>
            </Link>
          </div>
          <div className="voice-apply" role="status">
            {prepared.updating ? 'Preparing your daily and weekly editions…' : custom.data?.active ? 'Your custom character is ready.' : ''}
          </div>
          <ErrorNote error={save.error || prefs.error || prepared.error || selectCustom.error || preview.error} />
        </section>
        <section className="music-library" aria-label="Podcast library">
          <div className="music-section-heading">
            <h2>Your episodes</h2>
            <Link to="/briefings">Library</Link>
          </div>
          <div className="episode-grid">
            <button className="episode-card" onClick={() => selectEpisode('')}>
              <span className="episode-cover today">
                <AudioLines size={43} />
                <span className="episode-play">
                  <Play size={18} fill="currentColor" />
                </span>
              </span>
              <strong>
                {health.data?.news_reference_time
                  ? 'Prepared briefing'
                  : 'Daily podcast'}
              </strong>
              <span>
                {health.data?.news_reference_time
                  ? 'Archive edition'
                  : "Today's prepared edition"}
              </span>
            </button>
            <button
              className="episode-card"
              disabled={!weekly || weekly.status !== 'failed' && !prepared.weeklyPlayable}
              onClick={() => weekly && selectEpisode(weekly.id)}
            >
              <span className="episode-cover week">
                <AudioLines size={43} />
                <span className="episode-play">
                  <Play size={18} fill="currentColor" />
                </span>
              </span>
              <strong>This week</strong>
              <span>
                {weekly?.status === 'completed' ? prepared.weeklyPlayable ? clockTime(weekly.duration_seconds) + ' · Weekly briefing' : 'Loading audio…' : weekly?.status === 'failed' ? 'Needs attention' : 'Preparing…'}
              </span>
            </button>
            {episodes
              .filter((b) => b.id !== weekly?.id)
              .slice(0, 2)
              .map((b, i) => (
                <button
                  className="episode-card"
                  key={b.id}
                  onClick={() => selectEpisode(b.id)}
                >
                  <span className={'episode-cover archive color-' + i}>
                    <AudioLines size={43} />
                    <span className="episode-play">
                      <Play size={18} fill="currentColor" />
                    </span>
                  </span>
                  <strong>{b.title}</strong>
                  <span>
                    {niceDate(b.created_at)} · {clockTime(b.duration_seconds)}
                  </span>
                </button>
              ))}
          </div>
          <ErrorNote error={briefs.error} />
        </section>
        <footer className="music-footer">
          <Link to="/explore">Explore stories</Link>
          {(user.is_demo || user.is_admin) && (
            <Link to="/transparency">Transparency</Link>
          )}
          {health.data?.corpus === 'licensed' && (
            <span>Newstex hackathon archive</span>
          )}
          {user.is_demo && health.data?.corpus === 'demo' && (
            <span>Synthetic news demo</span>
          )}
        </footer>
      </main>
    </>
  )
}
