import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { AudioLines, Check, Play, Plus, LoaderCircle, Volume2, Lock } from 'lucide-react'
import { api, clockTime, niceDate, queryClient, useApi } from '../../api/client'
import type { Health } from '../../api/client'
import type { Briefing, Preferences, User } from '../../api/types'
import { SpeakerAvatar } from '../../components/SpeakerAvatar'
import { ErrorNote } from '../../components/UI'
import { customVoicePath } from '../voice/CustomVoice'
import { DailySession } from './DailySession'
import './studio.css'
import { VoiceEnginePicker } from '../voice/VoiceEnginePicker'
import { useVoicePreview } from '../voice/useVoicePreview'
import { VoiceCollection } from '../voice/VoiceCollection'
import { usePreparedEditions } from './usePreparedEditions'

export function StudioHome({ user }: { user: User }) {
  useEffect(() => {
    window.scrollTo(0, 0)
  }, [])
  const prefs = useApi<Preferences>('/users/me/preferences')
  const briefs = useApi<Briefing[]>('/briefings')
  const health = useApi<Health>('/health')
  const [searchParams] = useSearchParams()
  const notificationEdition = searchParams.get('briefing') || ''
  const [selectedId, setSelectedId] = useState(notificationEdition)
  useEffect(() => { setSelectedId(notificationEdition) }, [notificationEdition])
  const [playRequest, setPlayRequest] = useState(0)
  const prepared = usePreparedEditions()
  const engine = useMutation({
    mutationFn: (voice_engine: string) => api<Preferences>('/users/me/preferences', 'PATCH', { voice_engine }),
    onSuccess: data => {
      queryClient.setQueryData(['/users/me/preferences'], data)
      void queryClient.invalidateQueries({ queryKey: [customVoicePath] })
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
        <DailySession selectedId={selectedId} playRequest={playRequest} />
        <section className="music-voices" aria-label="Choose your voice">
          <div className="music-section-heading">
            <h2>Your voice</h2>
            <Link to="/settings?section=audio">Change voice</Link>
          </div>
          <VoiceEnginePicker value={prefs.data?.voice_engine || 'openai'} disabled={engine.isPending || !prefs.data}
            onChange={value => engine.mutate(value)} />
          <ErrorNote error={engine.error} />
          <VoiceCollection mode="home" prefs={prefs.data}/>
          <ErrorNote error={prefs.error || prepared.error}/>
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
