import { useState } from 'react'
import { useSearchParams, useNavigate } from 'react-router-dom'
import { useMutation } from '@tanstack/react-query'
import { Check, Clock3, Save } from 'lucide-react'
import { api, label, queryClient, useApi, type Health } from '../../api/client'
import type {
  Preferences,
  Schedule,
  Source,
  Topic,
  Voice,
} from '../../api/types'
import {
  Badge,
  Button,
  Card,
  Dropdown,
  ErrorNote,
  Loading,
} from '../../components/UI'
type Engine = {
  id: string
  name: string
  description: string
  available: boolean
}
import { VoiceSelector } from '../briefings/Briefings'
export function SchedulePicker({
  time,
  enabled,
  onTime,
  onEnabled,
}: {
  time: string
  enabled: boolean
  onTime: (s: string) => void
  onEnabled: (b: boolean) => void
}) {
  return (
    <div className="form-grid">
      <label className="check">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(e) => onEnabled(e.target.checked)}
        />
        <Clock3 size={16} />
        Daily briefing
      </label>
      <label className="field">
        Delivery time
        <input
          type="time"
          disabled={!enabled}
          required={enabled}
          value={time}
          onChange={(e) => onTime(e.target.value)}
        />
      </label>
    </div>
  )
}
export function Settings() {
  const health = useApi<Health>('/health')
  const p = useApi<Preferences>('/users/me/preferences'),
    s = useApi<Schedule[]>('/schedules'),
    src = useApi<Source[]>('/sources'),
    t = useApi<Topic[]>('/topics'),
    v = useApi<Voice[]>('/voices'),
    models = useApi<Engine[]>('/assistant/models')
  if ([p, s, src, t, v, models].some((q) => q.isPending)) return <Loading />
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
      key={s.data[0]?.id || 'no-schedule'}
      base={p.data}
      schedule={s.data[0]}
      sources={src.data}
      topics={t.data}
      voices={v.data}
      engines={models.data}
      elevenAgents={health.data?.conversation_provider === 'elevenagents'}
    />
  )
}
function SettingsForm({
  base,
  schedule,
  sources,
  topics,
  voices,
  engines,
  elevenAgents,
}: {
  base: Preferences
  schedule?: Schedule
  sources: Source[]
  topics: Topic[]
  voices: Voice[]
  engines: Engine[]
  elevenAgents: boolean
}) {
  const [prefs, setPrefs] = useState(base),
    [time, setTime] = useState(schedule?.time.slice(0, 5) || '08:00'),
    [enabled, setEnabled] = useState(schedule?.enabled || false),
    [extra, setExtra] = useState(''),
    [saved, setSaved] = useState(false),
    [currentSchedule, setCurrentSchedule] = useState(schedule?.id)
  const [params] = useSearchParams(),
    welcome = params.has('welcome'),
    navigate = useNavigate()
  const patch = <K extends keyof Preferences>(k: K, v: Preferences[K]) => {
    setSaved(false)
    setPrefs((p) => ({ ...p, [k]: v }))
  }
  const save = useMutation({
    mutationFn: async () => {
      if (!prefs.timezone.trim())
        throw new Error(
          'Enter an IANA time zone, for example Europe/Amsterdam.',
        )
      try {
        new Intl.DateTimeFormat('en', { timeZone: prefs.timezone })
      } catch {
        throw new Error(
          'Enter a valid IANA time zone, for example Europe/Amsterdam.',
        )
      }
      const updated = await api<Preferences>(
        '/users/me/preferences',
        'PATCH',
        prefs,
      )
      queryClient.setQueryData(['/users/me/preferences'], updated)
      const data = { time, enabled, timezone: prefs.timezone }
      if (currentSchedule || enabled) {
        const s = await api<Schedule>(
          currentSchedule ? '/schedules/' + currentSchedule : '/schedules',
          currentSchedule ? 'PATCH' : 'POST',
          data,
        )
        setCurrentSchedule(s.id)
        queryClient.setQueryData<Schedule[]>(['/schedules'], (previous) => [
          s,
          ...(previous || []).filter((r) => r.id !== s.id),
        ])
      }
    },
    onSuccess: () => {
      setSaved(true)
      queryClient.invalidateQueries({
        predicate: (q) => String(q.queryKey[0]).startsWith('/recommendations'),
      })
      if (welcome) navigate('/')
    },
  })
  const toggle = (k: 'interests', s: string) =>
    patch(
      k,
      prefs[k].includes(s) ? prefs[k].filter((t) => t !== s) : [...prefs[k], s],
    )
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
  return (
    <>
      <header className="page-heading">
        <div className="eyebrow">LISTENER PROFILE</div>
        <h1>{welcome ? 'Tune your briefing' : 'Listening preferences'}</h1>
      </header>
      <form
        className="settings form-stack"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <Card>
          <h2>Interests</h2>
          <div className="chips">
            {[
              ...new Set([...topics.map((t) => t.name), ...prefs.interests]),
            ].map((t) => (
              <button
                type="button"
                key={t}
                className={prefs.interests.includes(t) ? 'selected' : ''}
                aria-pressed={prefs.interests.includes(t)}
                onClick={() => toggle('interests', t)}
              >
                {prefs.interests.includes(t) && <Check size={14} />} {label(t)}
              </button>
            ))}
          </div>
          <label className="field">
            Custom interest
            <div className="inline-field">
              <input
                value={extra}
                onChange={(e) => setExtra(e.target.value)}
                maxLength={60}
                placeholder="Enter a topic"
              />
              <Button
                type="button"
                variant="outline"
                disabled={!extra.trim()}
                onClick={() => {
                  const val = extra.trim().toLowerCase().replace(/\s+/g, '_')
                  if (!prefs.interests.includes(val))
                    patch('interests', [...prefs.interests, val])
                  setExtra('')
                }}
              >
                Add
              </Button>
            </div>
          </label>
        </Card>
        <Card>
          <h2>Audio and language</h2>
          <div className="form-grid">
            <VoiceSelector
              voices={voices}
              value={prefs.voice_profile_id}
              onChange={(v) => patch('voice_profile_id', v)}
            />
            <Dropdown
              label="Language"
              value={prefs.language}
              onChange={(v) => patch('language', v)}
            >
              <option value="en">English</option>
              <option value="de">German</option>
              <option value="nl">Dutch</option>
            </Dropdown>
            <label className="field">
              Target minutes
              <input
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
            <Dropdown
              label="Depth"
              value={prefs.depth}
              onChange={(v) => patch('depth', v)}
            >
              {[...new Set([base.depth, 'brief', 'standard', 'detailed'])].map(
                (s) => (
                  <option key={s} value={s}>
                    {label(s)}
                  </option>
                ),
              )}
            </Dropdown>
          </div>
        </Card>
        <Card>
          <h2>{elevenAgents ? 'Text discussion model' : 'Discussion model'}</h2>
          <Dropdown
            label={elevenAgents ? 'Text assistant model' : 'Assistant model'}
            value={prefs.discussion_model}
            onChange={(v) => patch('discussion_model', v)}
          >
            {engines.map((m) => (
              <option key={m.id} value={m.id} disabled={!m.available}>
                {m.name}
              </option>
            ))}
          </Dropdown>
          <p className="muted">
            {engines.find((m) => m.id === prefs.discussion_model)?.description}
          </p>
          {elevenAgents && (
            <p className="muted">Live chat uses the voice and model configured in ElevenLabs.</p>
          )}
        </Card>
        <Card>
          <h2>Daily schedule</h2>
          <SchedulePicker
            time={time}
            enabled={enabled}
            onTime={(t) => {
              setTime(t)
              setSaved(false)
            }}
            onEnabled={(v) => {
              setEnabled(v)
              setSaved(false)
            }}
          />
          <label className="field">
            Time zone
            <input
              required
              value={prefs.timezone}
              onChange={(e) => patch('timezone', e.target.value)}
              placeholder="Europe/Amsterdam"
            />
          </label>
        </Card>
        <Card>
          <h2>Sources</h2>
          {sources.map((src) => (
            <div className="source-pref" key={src.id}>
              <div>
                {src.name} {src.is_synthetic && <Badge>Synthetic</Badge>}
              </div>
              <select
                aria-label={src.name + ' preference'}
                value={
                  prefs.preferred_sources.includes(src.id)
                    ? 'prefer'
                    : prefs.excluded_sources.includes(src.id)
                      ? 'exclude'
                      : 'normal'
                }
                onChange={(e) => sourceChoice(src.id, e.target.value)}
              >
                <option value="normal">Include</option>
                <option value="prefer">Prefer</option>
                <option value="exclude">Exclude</option>
              </select>
            </div>
          ))}
        </Card>
        <ErrorNote error={save.error} />
        <div className="action-row">
          <Button disabled={save.isPending}>
            <Save size={17} />
            {welcome ? 'Finish setup' : 'Save preferences'}
          </Button>
          {saved && (
            <span role="status" className="muted">
              Preferences saved.
            </span>
          )}
        </div>
      </form>
    </>
  )
}
