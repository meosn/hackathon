import { useState } from 'react'
import { ChevronDown, Plus, X } from 'lucide-react'
import { useApi } from '../../api/client'
import { ErrorNote } from '../../components/UI'
import { DAYS, TIMES, presetRoutine, type Frequency, type WeeklyRoutine } from './weeklySchedule'

export function TimeZoneSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const zones = useApi<string[]>('/timezones')
  const options = [...new Set([value, 'UTC', ...(zones.data || [])])].sort()
  return <>
    <label className="field">Time zone
      <select value={value} onChange={event => onChange(event.target.value)}>
        {options.map(zone => <option key={zone} value={zone}>{zone.replaceAll('_', ' ')}</option>)}
      </select>
    </label>
    <ErrorNote error={zones.error} />
  </>
}

export function SchedulePicker({ value, onChange }: { value: WeeklyRoutine; onChange: (value: WeeklyRoutine) => void }) {
  const [expanded, setExpanded] = useState(Math.max(0, value.days.findIndex(times => times.length)))
  function updateDay(day: number, times: string[]) {
    onChange({ ...value, frequency: 'custom', days: value.days.map((previous, index) => index === day ? times : previous) })
  }
  return <div className="routine-controls">
    <label className="routine-toggle">
      <span><strong>Scheduled briefings</strong><small>Have news ready on the days you choose.</small></span>
      <input className="preference-switch" aria-label="Scheduled briefings" type="checkbox" checked={value.enabled}
        onChange={event => onChange({ ...value, enabled: event.target.checked })} />
    </label>
    {value.enabled && <div className="weekly-routine">
      <label className="field">News frequency
        <select value={value.frequency} onChange={event => {
          const next = presetRoutine(value, event.target.value as Frequency)
          onChange(next)
          setExpanded(Math.max(0, next.days.findIndex(times => times.length)))
        }}>
          <option value="daily">Every day</option>
          <option value="twice-daily">Twice a day</option>
          <option value="weekdays">Weekdays</option>
          <option value="weekly">Once a week</option>
          <option value="twice-weekly">Twice a week</option>
          <option value="custom">Custom schedule</option>
        </select>
      </label>
      <p className="preference-hint">Set each day separately. Add more times for multiple briefings.</p>
      <div className="schedule-days">
        {DAYS.map((day, index) => {
          const times = value.days[index]
          const open = expanded === index && times.length > 0
          return <div className={'schedule-day' + (open ? ' expanded' : '')} key={day}>
            <div className="schedule-day-heading">
              <label className="schedule-day-choice">
                <input type="checkbox" aria-label={`${day} delivery`} checked={times.length > 0} onChange={event => {
                  updateDay(index, event.target.checked ? ['08:00'] : [])
                  if (event.target.checked) setExpanded(index)
                }} />
                <span>{day}</span>
              </label>
              <button type="button" className="schedule-day-expand" disabled={!times.length}
                aria-label={`Edit ${day} times`} aria-expanded={!!open} aria-controls={`schedule-times-${index}`}
                onClick={() => setExpanded(open ? -1 : index)}>
                <span>{times.length ? times.join(' · ') : 'Off'}</span><ChevronDown size={14} />
              </button>
            </div>
            {open && <div className="schedule-day-times" id={`schedule-times-${index}`}>
              {times.map((time, slot) => <div className="schedule-time-slot" key={slot}>
                <label className="field">{`Delivery ${slot + 1}`}
                  <select aria-label={`${day} delivery time ${slot + 1}`} value={time} onChange={event => updateDay(index,
                    times.map((previous, position) => position === slot ? event.target.value : previous))}>
                    {[...new Set([...TIMES, time])].sort().filter(option => option === time || !times.includes(option))
                      .map(option => <option key={option} value={option}>{option}</option>)}
                  </select>
                </label>
                <button type="button" className="schedule-remove-time" aria-label={`Remove ${day} delivery ${slot + 1}`}
                  onClick={() => updateDay(index, times.filter((_, position) => position !== slot))}><X size={15} /></button>
              </div>)}
              <button type="button" className="preference-text-button" disabled={times.length >= 12} onClick={() => {
                const last = [...times].sort().at(-1) || ''
                const next = ['08:00', '12:00', '18:00', '20:00', '22:00', ...TIMES].find(time => time > last && !times.includes(time))
                  || TIMES.find(time => !times.includes(time))
                if (next) updateDay(index, [...times, next].sort())
              }}><Plus size={14} /> Add a time</button>
            </div>}
          </div>
        })}
      </div>
    </div>}
  </div>
}
