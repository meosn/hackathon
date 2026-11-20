import type { Schedule } from '../../api/types'

export const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
export const TIMES = Array.from({ length: 288 }, (_, index) =>
  `${String(Math.floor(index / 12)).padStart(2, '0')}:${String(index % 12 * 5).padStart(2, '0')}`)
export type Frequency = 'daily' | 'twice-daily' | 'weekdays' | 'weekly' | 'twice-weekly' | 'custom'
export type WeeklyRoutine = { enabled: boolean; days: string[][]; frequency: Frequency }

function frequencyFor(days: string[][]): Frequency {
  const active = days.map((times, index) => times.length ? index : -1).filter(day => day >= 0)
  const first = days[active[0]] || []
  const same = active.every(day => JSON.stringify(days[day]) === JSON.stringify(first))
  if (same && first.length === 1) {
    if (active.length === 7) return 'daily'
    if (active.join(',') === '0,1,2,3,4') return 'weekdays'
    if (active.length === 1) return 'weekly'
    if (active.length === 2) return 'twice-weekly'
  }
  return same && first.length === 2 && active.length === 7 ? 'twice-daily' : 'custom'
}

export function routineFromSchedules(rows: Schedule[]): WeeklyRoutine {
  if (!rows.length) return { enabled: false, days: DAYS.map(() => ['08:00']), frequency: 'daily' }
  const enabled = rows.some(row => row.enabled)
  const active = enabled ? rows.filter(row => row.enabled) : rows
  const days = DAYS.map((_, day) => [...new Set(active
    .filter(row => (row.days_of_week || [0, 1, 2, 3, 4, 5, 6]).includes(day))
    .map(row => row.time.slice(0, 5)))].sort())
  return { enabled, days, frequency: frequencyFor(days) }
}

export function presetRoutine(current: WeeklyRoutine, frequency: Frequency): WeeklyRoutine {
  if (frequency === 'custom') return { ...current, frequency }
  const firstDay = Math.max(0, current.days.findIndex(times => times.length > 0))
  const time = current.days.flat()[0] || '08:00'
  const slots = frequency === 'twice-daily' ? [time, time === '18:00' ? '08:00' : '18:00'].sort() : [time]
  const selected = frequency === 'weekly' ? [firstDay]
    : frequency === 'twice-weekly' ? [firstDay, (firstDay + 3) % 7]
      : frequency === 'weekdays' ? [0, 1, 2, 3, 4] : [0, 1, 2, 3, 4, 5, 6]
  return { enabled: current.enabled, frequency, days: DAYS.map((_, day) => selected.includes(day) ? [...slots] : []) }
}

export function scheduleRows(routine: WeeklyRoutine, timezone: string) {
  const grouped = new Map<string, number[]>()
  routine.days.forEach((times, day) => {
    if (new Set(times).size !== times.length) throw Error('Choose different times for each delivery on the same day.')
    times.forEach(time => {
      if (!/^(?:[01]\d|2[0-3]):[0-5]\d$/.test(time)) throw Error('Choose a valid delivery time.')
      grouped.set(time, [...(grouped.get(time) || []), day])
    })
  })
  if (!grouped.size) {
    if (routine.enabled) throw Error('Choose at least one delivery day and time.')
    grouped.set('08:00', [0, 1, 2, 3, 4, 5, 6])
  }
  return [...grouped].sort(([a], [b]) => a.localeCompare(b)).map(([time, days_of_week]) =>
    ({ time, days_of_week, timezone, enabled: routine.enabled }))
}

export function routineSummary(routine: WeeklyRoutine) {
  if (!routine.enabled) return 'On your terms'
  const count = routine.days.flat().length
  if (routine.frequency === 'daily') return `Every day · ${routine.days[0][0]}`
  if (routine.frequency === 'twice-daily') return 'Twice a day'
  if (routine.frequency === 'weekly') {
    const day = routine.days.findIndex(times => times.length)
    return day < 0 ? 'Choose a day' : `${DAYS[day]} · ${routine.days[day][0]}`
  }
  return `${count} briefings per week`
}
