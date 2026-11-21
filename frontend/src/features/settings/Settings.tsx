import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import {
  ArrowLeft,
  ArrowRight,
  Check,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Globe2,
  Headphones,
  LoaderCircle,
  Search,
  SlidersHorizontal,
  Lock,
} from 'lucide-react'
import { api, label, queryClient, useApi } from '../../api/client'
import type {
  Preferences,
  Schedule,
  Source,
  Topic,
  Voice,
} from '../../api/types'
import { Button, Dropdown, ErrorNote, Loading } from '../../components/UI'
import { InterestPicker } from './InterestPicker'
import { CustomVoiceSettings } from '../voice/CustomVoice'
import { VoiceEnginePicker } from '../voice/VoiceEnginePicker'
import { SpeakerAvatar } from '../../components/SpeakerAvatar'
import { useVoicePreview } from '../voice/useVoicePreview'
import { PremiumNotice } from '../voice/PremiumNotice'
import { usePreparedEditions } from '../briefings/usePreparedEditions'
import { SchedulePicker, TimeZoneSelect } from './SchedulePicker'
import { routineFromSchedules, routineSummary, scheduleRows } from './weeklySchedule'
import { asGmtOffset, gmtOffset } from './gmtOffsets'
import './settings.css'

type Engine = {
  id: string
  name: string
  description: string
  available: boolean
}
const sections = [
  { id: 'briefing', name: 'Your briefing', icon: SlidersHorizontal },
  { id: 'audio', name: 'Voice & language', icon: Headphones },
  { id: 'routine', name: 'Daily routine', icon: Clock3 },
  { id: 'sources', name: 'Sources', icon: Globe2 },
] as const
type Section = (typeof sections)[number]['id']
const languages: Record<string, string> = {
  en: 'English',
  de: 'German',
  nl: 'Dutch',
}
const pageSize = 7

export function Settings() {
  const p = useApi<Preferences>('/users/me/preferences'),
    s = useApi<Schedule[]>('/schedules'),
    src = useApi<Source[]>('/sources'),
    t = useApi<Topic[]>('/topics'),
    v = useApi<Voice[]>('/voices'),
    models = useApi<Engine[]>('/assistant/models')
  if ([p, s, src, t, v, models].some((q) => q.isPending))
    return <Loading>Opening preferences…</Loading>
  if (!p.data || !s.data || !src.data || !t.data || !v.data || !models.data)
    return (
      <ErrorNote
        error={
          p.error || s.error || src.error || t.error || v.error || models.error
        }
      />
    )
  return (
    <SettingsForm
      base={p.data}
      schedules={s.data}
      sources={src.data}
      topics={t.data}
      voices={v.data}
      engines={models.data}
    />
  )
}

function SettingsForm({
  base,
  schedules,
  sources,
  topics,
  voices,
  engines,
}: {
  base: Preferences
  schedules: Schedule[]
  sources: Source[]
  topics: Topic[]
  voices: Voice[]
  engines: Engine[]
}) {
  const [prefs, setPrefs] = useState(base)
  const preview = useVoicePreview()
  const [premiumNotice, setPremiumNotice] = useState(false)
  const [defaultNarrator, setDefaultNarrator] = useState(false)
  const prepared = usePreparedEditions()
  const elevenAgents = prefs.voice_engine === 'elevenlabs'
  const [routine, setRoutine] = useState(() => routineFromSchedules(schedules))
  const [saved, setSaved] = useState(false)
  const [snapshot, setSnapshot] = useState({ prefs: base, routine })
  useEffect(() => {
    setPrefs(previous => ({ ...previous, voice_engine: base.voice_engine }))
    setSnapshot(previous => ({ ...previous, prefs: { ...previous.prefs, voice_engine: base.voice_engine } }))
  }, [base.voice_engine])
  const [sourceSearch, setSourceSearch] = useState('')
  const [sourceFilter, setSourceFilter] = useState('all')
  const [page, setPage] = useState(0)
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const welcome = params.has('welcome')
  const selected = params.get('section')
  const section: Section = sections.some((s) => s.id === selected)
    ? (selected as Section)
    : 'briefing'
  const tabs = useRef<(HTMLButtonElement | null)[]>([])
  const dirty =
    JSON.stringify({ prefs, routine }) !== JSON.stringify(snapshot)
  const voice = voices.find((v) => v.id === prefs.voice_profile_id)
  const summaries = {
    briefing: `${prefs.interests.length} interests · ${label(prefs.depth)}`,
    audio: `${voice?.name || 'Choose a voice'} · ${languages[prefs.language] || prefs.language}`,
    routine: routineSummary(routine),
    sources: `${prefs.preferred_sources.length} preferred · ${prefs.excluded_sources.length} excluded`,
  }
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => event.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
  const patch = <K extends keyof Preferences>(k: K, v: Preferences[K]) => {
    setSaved(false)
    setPrefs((p) => ({ ...p, [k]: v }))
  }
  function selectSection(id: Section) {
    setParams(
      (previous) => {
        previous.set('section', id)
        return previous
      },
      { replace: true },
    )
  }
  const save = useMutation({
    mutationFn: async () => {
      if (
        !Number.isInteger(prefs.duration_minutes) ||
        prefs.duration_minutes < 1 ||
        prefs.duration_minutes > 30
      ) {
        selectSection('briefing')
        throw new Error('Choose a briefing length between 1 and 30 minutes.')
      }
      const timezone = asGmtOffset(prefs.timezone) || prefs.timezone
      let rows
      try { rows = scheduleRows(routine, timezone) }
      catch (error) {
        selectSection('routine')
        throw error
      }
      try {
        if (!prefs.timezone.trim()) throw new Error()
      } catch {
        selectSection('routine')
        throw new Error(
          'Choose a valid time zone.',
        )
      }
      const updated = await api<Preferences>(
        '/users/me/preferences',
        'PATCH',
        { ...prefs, timezone },
      )
      queryClient.setQueryData(['/users/me/preferences'], updated)
      const savedSchedules = await api<Schedule[]>('/schedules', 'PUT', rows)
      queryClient.setQueryData(['/schedules'], savedSchedules)
      if (defaultNarrator) {
        await api('/users/me/custom-voice', 'PATCH', { active: false })
        void queryClient.invalidateQueries({ queryKey: ['/users/me/custom-voice'] })
        setDefaultNarrator(false)
      }
      await api('/briefings/prepare', 'POST')
      void queryClient.invalidateQueries({ queryKey: ['prepared-editions'] })
      const savedRoutine = routineFromSchedules(savedSchedules)
      setPrefs(updated)
      setRoutine(savedRoutine)
      setSnapshot({ prefs: updated, routine: savedRoutine })
    },
    onSuccess: () => {
      setSaved(true)
      queryClient.invalidateQueries({
        predicate: (q) => String(q.queryKey[0]).startsWith('/recommendations'),
      })
      if (welcome) navigate('/')
    },
  })
  function sourceChoice(id: string, value: string) {
    setSaved(false)
    setPrefs((p) => ({
      ...p,
      preferred_sources: [
        ...p.preferred_sources.filter((i) => i !== id),
        ...(value === 'prefer' ? [id] : []),
      ],
      excluded_sources: [
        ...p.excluded_sources.filter((i) => i !== id),
        ...(value === 'exclude' ? [id] : []),
      ],
    }))
  }
  const filteredSources = sources.filter(
    (s) =>
      s.name.toLowerCase().includes(sourceSearch.trim().toLowerCase()) &&
      (sourceFilter === 'all' ||
        (sourceFilter === 'preferred'
          ? prefs.preferred_sources
          : prefs.excluded_sources
        ).includes(s.id)),
  )
  const pages = Math.max(1, Math.ceil(filteredSources.length / pageSize))
  const activePage = Math.min(page, pages - 1)
  const visibleSources = filteredSources.slice(
    activePage * pageSize,
    (activePage + 1) * pageSize,
  )


  return (
    <div className="preferences-page">
      {premiumNotice && <PremiumNotice onClose={() => setPremiumNotice(false)} />}
      {saved && prepared.updating && <p className="preference-hint" role="status">Preparing your updated daily and weekly editions…</p>}
      <Link to="/" className="preferences-back">
        <ArrowLeft size={15} /> Listening room
      </Link>
      <header className="preferences-heading">
        <div>
          <span className="preferences-eyebrow">A LITTLE MORE YOU</span>
          <h1>{welcome ? 'Tune your briefing' : 'Listening preferences'}</h1>
          <p>Your news. Your voice. Your pace.</p>
        </div>
        <span className="preferences-heading-icon" aria-hidden="true">
          <SlidersHorizontal size={26} strokeWidth={1.3} />
        </span>
      </header>
      <form
        className="preferences-form"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <div className="preferences-layout">
          <aside className="preferences-sidebar">
            <div
              className="preferences-tabs"
              role="tablist"
              aria-label="Preference sections"
              aria-orientation="vertical"
              onKeyDown={(event) => {
                const index = sections.findIndex((s) => s.id === section)
                const direction = ['ArrowDown', 'ArrowRight'].includes(
                  event.key,
                )
                  ? 1
                  : ['ArrowUp', 'ArrowLeft'].includes(event.key)
                    ? -1
                    : 0
                const next =
                  event.key === 'Home'
                    ? 0
                    : event.key === 'End'
                      ? sections.length - 1
                      : (index + direction + sections.length) % sections.length
                if (!direction && !['Home', 'End'].includes(event.key)) return
                event.preventDefault()
                selectSection(sections[next].id)
                tabs.current[next]?.focus()
              }}
            >
              {sections.map(({ id, name, icon: Icon }, i) => (
                <button
                  key={id}
                  ref={(el) => {
                    tabs.current[i] = el
                  }}
                  type="button"
                  role="tab"
                  id={'tab-' + id}
                  aria-controls="preferences-panel"
                  aria-selected={section === id}
                  tabIndex={section === id ? 0 : -1}
                  onClick={() => selectSection(id)}
                >
                  <Icon size={18} strokeWidth={1.6} />
                  <span>
                    <strong>{name}</strong>
                    <small>{summaries[id]}</small>
                  </span>
                  <ChevronRight size={14} className="tab-chevron" />
                </button>
              ))}
            </div>
            <div className="edition-preview" aria-label="Your edition preview">
              <div className="edition-preview-label">
                <span className="edition-dot" /> MADE FOR YOU
              </div>
              <div className="edition-wave" aria-hidden="true">
                {[
                  12, 23, 16, 36, 25, 46, 32, 19, 39, 27, 46, 31, 18, 26, 14,
                  20, 10,
                ].map((h, i) => (
                  <i key={i} style={{ height: h }} />
                ))}
              </div>
              <strong>Good news. On your terms.</strong>
              <p>
                {voice?.name || 'Your voice'} in{' '}
                {languages[prefs.language] || prefs.language}.
              </p>
              <span>3 top stories. More whenever you ask.</span>
            </div>
          </aside>
          <div
            className="preferences-panel"
            role="tabpanel"
            id="preferences-panel"
            aria-labelledby={'tab-' + section}
            tabIndex={0}
          >
            <fieldset disabled={save.isPending} className="preferences-fields">
              {section === 'briefing' && (
                <>
                  <div className="preference-section-heading">
                    <span className="preferences-eyebrow">
                      01 / YOUR BRIEFING
                    </span>
                    <h2>Follow your curiosity.</h2>
                    <p>
                      Choose what matters. We’ll find the stories worth your
                      time.
                    </p>
                  </div>
                  <section className="preference-block">
                    <div className="preference-label">
                      <h3>Your interests</h3>
                      <span>{prefs.interests.length} selected</span>
                    </div>
                    <InterestPicker topics={topics.map(t => t.name)} selected={prefs.interests} custom={prefs.custom_topics || []}
                      onChange={(interests, custom_topics) => { setSaved(false); setPrefs(p => ({ ...p, interests, custom_topics })) }} />
                    <p className="preference-hint">Your choices and story reactions shape future editions. Switching a topic off keeps it in your list.</p>
                    {prefs.interests.length === 0 && (
                      <p className="preference-hint">
                        Open to everything. You’ll hear a balanced selection of
                        stories.
                      </p>
                    )}
                  </section>
                  <section className="preference-block">
                    <div className="preference-label">
                      <h3>How deep do we go?</h3>
                    </div>
                    <div className="depth-options">
                      {[
                        ...new Set([
                          'brief',
                          'standard',
                          'detailed',
                          base.depth,
                        ]),
                      ].map((depth) => (
                        <button
                          key={depth}
                          type="button"
                          aria-pressed={prefs.depth === depth}
                          onClick={() => patch('depth', depth)}
                        >
                          <span className="depth-mark" aria-hidden="true">
                            {[0, 1, 2].map((i) => (
                              <i
                                key={i}
                                className={
                                  i <=
                                  ['brief', 'standard', 'detailed'].indexOf(
                                    depth,
                                  )
                                    ? 'filled'
                                    : ''
                                }
                              />
                            ))}
                          </span>
                          <strong>{label(depth)}</strong>
                          <small>
                            {depth === 'brief'
                              ? 'Just the essentials'
                              : depth === 'standard'
                                ? 'A little more context'
                                : 'The fuller picture'}
                          </small>
                        </button>
                      ))}
                    </div>
                  </section>
                  <section className="preference-block">
                    <div className="preference-label">
                      <h3>Your preferred length</h3>
                      <span>{prefs.duration_minutes} min</span>
                    </div>
                    <div
                      className="duration-options"
                      aria-label="Preferred length"
                    >
                      {[3, 5, 10, 15].map((n) => (
                        <button
                          key={n}
                          type="button"
                          aria-pressed={prefs.duration_minutes === n}
                          onClick={() => patch('duration_minutes', n)}
                        >
                          {n} min
                        </button>
                      ))}
                      <label className="custom-duration">
                        <span>Custom</span>
                        <input
                          aria-label="Target minutes"
                          type="number"
                          min={1}
                          max={30}
                          required
                          value={prefs.duration_minutes}
                          onChange={(e) =>
                            patch('duration_minutes', Number(e.target.value))
                          }
                        />
                      </label>
                    </div>
                    <p className="preference-hint">
                      Applies to daily, custom and weekly editions. Longer daily
                      briefings add detail to the same top 3 stories.
                    </p>
                  </section>
                </>
              )}
              {section === 'audio' && (
                <>
                  <div className="preference-section-heading">
                    <span className="preferences-eyebrow">
                      02 / VOICE & LANGUAGE
                    </span>
                    <h2>Find your frequency.</h2>
                    <p>A familiar voice. A language that feels like home.</p>
                  </div>
                  <section className="preference-block">
                    <h3>Voice model</h3>
                    <VoiceEnginePicker value={prefs.voice_engine} onChange={value => patch('voice_engine', value)} />
                    <p className="preference-hint">Applied to your next live conversation. Custom voices use ElevenLabs.</p>
                  </section>
                  <section className="preference-block">
                    <div className="preference-label">
                      <h3>Your narrator</h3>
                      <span>One voice, every edition</span>
                    </div>
                    <div className="narrator-options">
                      {voices.map((v) => (
                        <button
                          key={v.id}
                          type="button"
                          aria-pressed={prefs.voice_profile_id === v.id}
                          title={'Preview and select ' + v.name}
                          onClick={() => {
                            if (v.locked) { setPremiumNotice(true); return }
                            setDefaultNarrator(true)
                            preview.play(v.id, v.id === 'energetic' ? 'elevenlabs' : prefs.voice_engine, prefs.language)
                            patch('voice_profile_id', v.id)
                            if (v.id === 'energetic') patch('voice_engine', 'elevenlabs')
                          }}
                        >
                          <span className="narrator-symbol"><SpeakerAvatar id={v.id} /></span>
                          <span>
                            <strong>{v.name}</strong>
                            <small>{v.description}</small>
                          </span>
                          <span className="selection-circle">
                            {v.locked ? <Lock size={14} /> : prefs.voice_profile_id === v.id && (
                              <Check size={12} />
                            )}
                          </span>
                        </button>
                      ))}
                    </div>
                    <ErrorNote error={preview.error} />
                    <p className="preference-hint">
                      Used for new editions and live replies. OpenAI uses the character’s delivery with an OpenAI voice.
                    </p>
                  </section>
                  <CustomVoiceSettings />
                  <section className="preference-block">
                    <div className="preference-label">
                      <h3>Briefing language</h3>
                    </div>
                    <div className="language-options">
                      {Object.entries(languages).map(([id, name]) => (
                        <button
                          type="button"
                          key={id}
                          aria-pressed={prefs.language === id}
                          onClick={() => patch('language', id)}
                        >
                          <span>{id.toUpperCase()}</span>
                          {name}
                          {prefs.language === id && <Check size={14} />}
                        </button>
                      ))}
                    </div>
                  </section>
                  <details className="advanced-preferences">
                    <summary>
                      Fine-tune your assistant
                      <ChevronDown size={15} />
                    </summary>
                    <div>
                      <Dropdown
                        label={
                          elevenAgents
                            ? 'Text assistant model'
                            : 'Assistant model'
                        }
                        value={prefs.discussion_model}
                        onChange={(v) => patch('discussion_model', v)}
                      >
                        {engines.map((m) => (
                          <option
                            key={m.id}
                            value={m.id}
                            disabled={!m.available}
                          >
                            {m.name}
                          </option>
                        ))}
                      </Dropdown>
                      <p className="preference-hint">
                        {
                          engines.find((m) => m.id === prefs.discussion_model)
                            ?.description
                        }
                      </p>
                    </div>
                  </details>
                </>
              )}
              {section === 'routine' && (
                <>
                  <div className="preference-section-heading">
                    <span className="preferences-eyebrow">
                      03 / DAILY ROUTINE
                    </span>
                    <h2>A moment for the world.</h2>
                    <p>Make your briefing part of your day.</p>
                  </div>
                  <div className="schedule-overview">
                    <Clock3 size={22} strokeWidth={1.3} />
                    <div><strong>{routineSummary(routine)}</strong><small>All times follow your selected time zone.</small></div>
                  </div>
                  <section className="preference-block">
                    <SchedulePicker value={routine} onChange={value => { setRoutine(value); setSaved(false) }} />
                  </section>
                  <section className="preference-block">
                    <TimeZoneSelect value={prefs.timezone} onChange={value => patch('timezone', value)} />
                    <button
                      className="preference-text-button"
                      type="button"
                      onClick={() =>
                        patch(
                          'timezone',
                          gmtOffset(-new Date().getTimezoneOffset()),
                        )
                      }
                    >
                      <Globe2 size={14} /> Use my current GMT offset
                    </button>
                    <p className="preference-hint">Scheduled editions appear in your <Link to="/briefings">briefing library</Link>.</p>
                  </section>
                </>
              )}
              {section === 'sources' && (
                <>
                  <div className="preference-section-heading">
                    <span className="preferences-eyebrow">04 / SOURCES</span>
                    <h2>A considered perspective.</h2>
                    <p>
                      Bring trusted voices closer. Make room for a wider view.
                    </p>
                  </div>
                  <div className="source-toolbar">
                    <label className="source-search">
                      <Search size={16} />
                      <input
                        type="search"
                        aria-label="Search sources"
                        placeholder={`Search ${sources.length} sources`}
                        value={sourceSearch}
                        onChange={(e) => {
                          setSourceSearch(e.target.value)
                          setPage(0)
                        }}
                      />
                    </label>
                    <div className="source-filter" aria-label="Filter sources">
                      {[
                        ['all', 'All'],
                        ['preferred', 'Preferred'],
                        ['excluded', 'Excluded'],
                      ].map(([id, name]) => (
                        <button
                          key={id}
                          type="button"
                          aria-pressed={sourceFilter === id}
                          onClick={() => {
                            setSourceFilter(id)
                            setPage(0)
                          }}
                        >
                          {name}
                        </button>
                      ))}
                    </div>
                  </div>
                  <div className="source-list-header">
                    <span>PUBLICATION</span>
                    <span>YOUR PREFERENCE</span>
                  </div>
                  <div className="preference-sources">
                    {visibleSources.map((src) => (
                      <div className="preference-source" key={src.id}>
                        <span className="publication-mark" aria-hidden="true">
                          {src.name.slice(0, 1).toUpperCase()}
                        </span>
                        <div className="publication-name">
                          <strong>{src.name}</strong>
                          {src.is_synthetic && <small>Synthetic source</small>}
                        </div>
                        <span className="source-select">
                          <select
                            aria-label={src.name + ' preference'}
                            value={
                              prefs.preferred_sources.includes(src.id)
                                ? 'prefer'
                                : prefs.excluded_sources.includes(src.id)
                                  ? 'exclude'
                                  : 'normal'
                            }
                            onChange={(e) =>
                              sourceChoice(src.id, e.target.value)
                            }
                          >
                            <option value="normal">Include</option>
                            <option value="prefer">Prefer</option>
                            <option value="exclude">Exclude</option>
                          </select>
                          <ChevronDown size={13} />
                        </span>
                      </div>
                    ))}
                  </div>
                  {visibleSources.length === 0 && (
                    <div className="sources-empty">
                      <Search size={23} strokeWidth={1.3} />
                      <strong>
                        {sourceSearch
                          ? 'No matching publications'
                          : `No ${sourceFilter} sources yet`}
                      </strong>
                      <p>
                        {sourceSearch
                          ? 'Try another name or clear your search.'
                          : 'Change a publication’s preference in All sources.'}
                      </p>
                      <button
                        type="button"
                        className="preference-text-button"
                        onClick={() => {
                          setSourceSearch('')
                          setSourceFilter('all')
                          setPage(0)
                        }}
                      >
                        Show all sources
                        <ArrowRight size={14} />
                      </button>
                    </div>
                  )}
                  <div className="sources-pagination">
                    <span>
                      {filteredSources.length
                        ? `${activePage * pageSize + 1}–${Math.min((activePage + 1) * pageSize, filteredSources.length)} of ${filteredSources.length} sources`
                        : '0 sources'}
                    </span>
                    {pages > 1 && (
                      <div>
                        <button
                          type="button"
                          aria-label="Previous sources"
                          disabled={activePage === 0}
                          onClick={() => setPage(activePage - 1)}
                        >
                          <ChevronLeft size={16} />
                        </button>
                        <span>
                          {activePage + 1} / {pages}
                        </span>
                        <button
                          type="button"
                          aria-label="Next sources"
                          disabled={activePage === pages - 1}
                          onClick={() => setPage(activePage + 1)}
                        >
                          <ChevronRight size={16} />
                        </button>
                      </div>
                    )}
                  </div>
                  <p className="preference-hint">
                    Preferred sources get more weight. Excluded sources stay out
                    of future editions.
                  </p>
                </>
              )}
            </fieldset>
          </div>
        </div>
        {(dirty || saved || welcome || save.isPending || save.error) && (
          <footer
            className={'preferences-savebar ' + (dirty ? 'has-changes' : '')}
          >
            <div className="preferences-save-status" role="status">
              {save.isPending ? (
                <>
                  <LoaderCircle size={15} className="spin" /> Saving your
                  preferences…
                </>
              ) : dirty ? (
                <>
                  <span className="unsaved-dot" /> Unsaved changes
                </>
              ) : saved ? (
                <>
                  <Check size={16} /> Preferences saved.
                </>
              ) : (
                <>
                  <Check size={15} /> All set. Make yourself at home.
                </>
              )}
            </div>
            <div className="preferences-save-actions">
              {dirty && (
                <button
                  type="button"
                  disabled={save.isPending}
                  className="preference-text-button"
                  onClick={() => {
                    setPrefs(snapshot.prefs)
                    setRoutine(snapshot.routine)
                    setSaved(false)
                    save.reset()
                  }}
                >
                  Discard
                </button>
              )}
              <Button disabled={save.isPending || (!dirty && !welcome)}>
                {save.isPending
                  ? 'Saving…'
                  : welcome
                    ? 'Finish setup'
                    : 'Save preferences'}
                {!save.isPending && <ArrowRight size={15} />}
              </Button>
            </div>
            <ErrorNote error={save.error} />
          </footer>
        )}
      </form>
    </div>
  )
}
