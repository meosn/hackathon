import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AudioLines, Check, Play } from 'lucide-react'
import { api, clockTime, niceDate, queryClient, useApi } from '../../api/client'
import type { Health } from '../../api/client'
import type { Briefing, Preferences, User } from '../../api/types'
import { ErrorNote } from '../../components/UI'
import { DailySession } from './DailySession'
import './studio.css'

const hosts = [
  { id: 'professional', name: 'The Anchor', look: 'anchor' },
  { id: 'casual', name: 'Street Signal', look: 'street' },
  { id: 'jarvis', name: 'Studio Assistant', look: 'assistant' },
]
function Portrait({ look }: { look: string }) {
  return (
    <div className={'host-portrait abstract-voice ' + look} aria-hidden="true">
      <AudioLines size={42} strokeWidth={1} />
    </div>
  )
}
export function StudioHome({ user }: { user: User }) {
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])
  const prefs = useApi<Preferences>('/users/me/preferences')
  const briefs = useApi<Briefing[]>('/briefings')
  const health = useApi<Health>('/health')
  const [selectedId, setSelectedId] = useState('')
  const [playRequest, setPlayRequest] = useState(0)
  const [voiceChanged, setVoiceChanged] = useState(false)
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
          <div className="music-hosts">
            {hosts.map((host) => (
              <button
                type="button"
                key={host.id}
                aria-pressed={prefs.data?.voice_profile_id === host.id}
                className="music-host"
                disabled={save.isPending || !prefs.data}
                onClick={() => save.mutate(host.id)}
              >
                <span className="portrait-wrap">
                  <Portrait look={host.look} />
                  {prefs.data?.voice_profile_id === host.id && (
                    <span className="voice-check">
                      <Check size={13} />
                    </span>
                  )}
                </span>
                <span>{host.name}</span>
              </button>
            ))}
          </div>
          <div className="voice-apply" role="status">
            {voiceChanged ? (
              <>
                <span>Voice selected.</span>
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
          <ErrorNote error={save.error || prefs.error || generate.error} />
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
