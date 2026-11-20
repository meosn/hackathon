import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AudioLines, Check, Play, Plus } from 'lucide-react'
import { api, clockTime, niceDate, queryClient, useApi } from '../../api/client'
import type { Health } from '../../api/client'
import type { Briefing, Preferences, User } from '../../api/types'
import { SpeakerAvatar } from '../../components/SpeakerAvatar'
import { ErrorNote } from '../../components/UI'
import { customVoicePath, setCustomVoice, type CustomVoiceState } from '../voice/CustomVoice'
import { DailySession } from './DailySession'
import './studio.css'
import { VoiceEnginePicker } from '../voice/VoiceEnginePicker'

const hosts = [
  { id: 'professional', name: 'The Anchor' },
  { id: 'casual', name: 'Street Signal' },
  { id: 'jarvis', name: 'Studio Assistant' },
  { id: 'energetic', name: 'Energetic Speaker' },
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
  const [voiceChanged, setVoiceChanged] = useState(false)
  const engine = useMutation({
    mutationFn: (voice_engine: string) => api<Preferences>('/users/me/preferences', 'PATCH', { voice_engine }),
    onSuccess: data => {
      queryClient.setQueryData(['/users/me/preferences'], data)
      void queryClient.invalidateQueries({ queryKey: [customVoicePath] })
    },
  })
  const save = useMutation({
    mutationFn: (voice_profile_id: string) =>
      api<Preferences>('/users/me/preferences', 'PATCH', { voice_profile_id }),
    onMutate: async (voice_profile_id) => {
      await queryClient.cancelQueries({ queryKey: ['/users/me/preferences'] })
      const previous = queryClient.getQueryData<Preferences>([
        '/users/me/preferences',
      ])
      if (previous)
        queryClient.setQueryData(['/users/me/preferences'], {
          ...previous,
          voice_profile_id,
        })
      return { previous }
    },
    onError: (_error, _voice, context) => {
      if (context?.previous)
        queryClient.setQueryData(['/users/me/preferences'], context.previous)
    },
    onSuccess: (data) => {
      queryClient.setQueryData(['/users/me/preferences'], data)
      setVoiceChanged(true)
    },
  })
  const generate = useMutation({
    mutationFn: (period: 'day' | 'week') =>
      api<{ briefing_id: string }>('/briefings', 'POST', {
        period,
        ...(period === 'day' ? { story_limit: 3 } : {}),
      }),
    onSuccess: (r) => {
      selectEpisode(r.briefing_id)
      setVoiceChanged(false)
      void briefs.refetch()
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
  const weekly = briefs.data?.find(
    (b) => b.period === 'week' && b.status === 'completed',
  )
  return (
    <>
      <main id="main" className="music-main">
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
                className="music-host"
                disabled={save.isPending || selectCustom.isPending || !prefs.data}
                onClick={async () => {
                  if (custom.data?.active) {
                    try { await selectCustom.mutateAsync(false) } catch { return }
                  }
                  save.mutate(host.id)
                }}
              >
                <span className="portrait-wrap">
                  <SpeakerAvatar id={host.id} />
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
                onClick={() => { setVoiceChanged(false); selectCustom.mutate(true) }}>
                <span className="portrait-wrap">
                  <span className="speaker-avatar custom-voice-icon" aria-hidden="true">C</span>
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
            {custom.data?.active && prefs.data?.voice_engine === 'elevenlabs' ? 'Custom voice selected for ElevenLabs live chat.' : voiceChanged ? (
              <>
                <span>New replies use this voice.</span>
                <button
                  onClick={() => generate.mutate('day')}
                  disabled={generate.isPending}
                >
                  Create with this voice
                </button>
              </>
            ) : save.isPending ? (
              'Saving voice…'
            ) : null}
          </div>
          <ErrorNote error={save.error || prefs.error || generate.error || selectCustom.error} />
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
              disabled={generate.isPending}
              onClick={() =>
                weekly ? selectEpisode(weekly.id) : generate.mutate('week')
              }
            >
              <span className="episode-cover week">
                <AudioLines size={43} />
                <span className="episode-play">
                  <Play size={18} fill="currentColor" />
                </span>
              </span>
              <strong>This week</strong>
              <span>
                {weekly
                  ? clockTime(weekly.duration_seconds) + ' · Weekly briefing'
                  : generate.isPending
                    ? 'Preparing…'
                    : 'Create a weekly edition'}
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
