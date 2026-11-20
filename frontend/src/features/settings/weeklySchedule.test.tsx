import { useState } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, expect, it, vi } from 'vitest'
import type { Schedule } from '../../api/types'
import { SchedulePicker, TimeZoneSelect } from './SchedulePicker'
import { asGmtOffset, gmtLabel, GMT_ZONES } from './gmtOffsets'
import { routineFromSchedules, scheduleRows, type WeeklyRoutine } from './weeklySchedule'

afterEach(() => vi.restoreAllMocks())
function Harness() {
  const [routine, setRoutine] = useState(routineFromSchedules([]))
  return <><SchedulePicker value={routine} onChange={setRoutine} /><output data-testid="routine">{JSON.stringify(routine)}</output></>
}
const plan = () => JSON.parse(screen.getByTestId('routine').textContent!) as WeeklyRoutine

it('offers frequency presets and lets Monday change without changing Tuesday', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scheduled briefings' }))
  fireEvent.change(screen.getByRole('combobox', { name: 'News frequency' }), { target: { value: 'twice-daily' } })
  expect(plan().days.every(times => times.join(',') === '08:00,18:00')).toBe(true)
  const hours = screen.getByRole('combobox', { name: 'Monday delivery 1 hours' })
  const minutes = screen.getByRole('combobox', { name: 'Monday delivery 1 minutes' })
  expect(hours.querySelectorAll('option')).toHaveLength(24)
  expect(minutes.querySelectorAll('option')).toHaveLength(60)
  fireEvent.change(hours, { target: { value: '09' } })
  fireEvent.change(minutes, { target: { value: '17' } })
  expect(plan().days[0]).toEqual(['09:17', '18:00'])
  expect(plan().frequency).toBe('twice-daily')
  expect(plan().days[1]).toEqual(['08:00', '18:00'])
  fireEvent.click(screen.getByRole('button', { name: 'Remove Monday delivery 2' }))
  expect(plan().days[0]).toEqual(['09:17'])
  expect(plan().days[1]).toHaveLength(2)
  fireEvent.click(screen.getByRole('button', { name: 'Add a time' }))
  expect(plan().days[0]).toHaveLength(2)
})

it('supports one or two weekly days and disables individual days', () => {
  render(<Harness />)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Scheduled briefings' }))
  const frequency = screen.getByRole('combobox', { name: 'News frequency' })
  fireEvent.change(frequency, { target: { value: 'weekly' } })
  expect(plan().days.filter(times => times.length)).toHaveLength(1)
  fireEvent.change(frequency, { target: { value: 'twice-weekly' } })
  expect(plan().days.filter(times => times.length)).toHaveLength(2)
  fireEvent.click(screen.getByRole('checkbox', { name: 'Monday delivery' }))
  expect(plan().days[0]).toEqual([])
  expect(plan().days[3]).toEqual(['08:00'])
})

it('round-trips grouped weekday times and retains a disabled plan for later', () => {
  const rows = [
    { id: 'morning', time: '08:00', timezone: 'Europe/Berlin', days_of_week: [0, 2], enabled: true },
    { id: 'evening', time: '18:30', timezone: 'Europe/Berlin', days_of_week: [0], enabled: true },
  ] as Schedule[]
  const routine = routineFromSchedules(rows)
  expect(routine.days[0]).toEqual(['08:00', '18:30'])
  expect(routine.days[1]).toEqual([])
  expect(scheduleRows(routine, 'Europe/Berlin')).toEqual(rows.map(({ id: _id, ...row }) => row))
  const disabled = routineFromSchedules(scheduleRows({ ...routine, enabled: false }, 'Europe/Berlin') as Schedule[])
  expect(disabled.enabled).toBe(false)
  expect(disabled.days).toEqual(routine.days)
  expect(() => scheduleRows({ ...routine, days: [[], [], [], [], [], [], []] }, 'UTC')).toThrow('at least one')
})

it('shows short GMT offsets without city names and accepts fractional offsets', async () => {
  vi.spyOn(globalThis, 'fetch').mockResolvedValue(Response.json(GMT_ZONES))
  const changed = vi.fn()
  render(<QueryClientProvider client={new QueryClient()}><TimeZoneSelect value="UTC" onChange={changed} /></QueryClientProvider>)
  const select = screen.getByRole('combobox', { name: 'Time zone' })
  await waitFor(() => expect(screen.getByRole('option', { name: /^GMT\+2$/ })).toBeInTheDocument())
  fireEvent.change(select, { target: { value: 'GMT+02:00' } })
  expect(changed).toHaveBeenCalledWith('GMT+02:00')
  expect(screen.getByRole('option', { name: 'GMT+5:45' })).toBeInTheDocument()
  expect(screen.queryByRole('option', { name: /Europe|America/ })).toBeNull()
  expect(screen.queryByRole('textbox')).toBeNull()
})

it('displays saved regional zones at their current GMT offset', () => {
  expect(asGmtOffset('Europe/Berlin', new Date('2026-11-21T12:00:00Z'))).toBe('GMT+01:00')
  expect(asGmtOffset('Europe/Berlin', new Date('2026-07-21T12:00:00Z'))).toBe('GMT+02:00')
  expect(asGmtOffset('Asia/Kathmandu')).toBe('GMT+05:45')
  expect(asGmtOffset('GMT-03:30')).toBe('GMT-03:30')
  expect(gmtLabel('GMT-03:30')).toBe('GMT-3:30')
  expect(asGmtOffset('Unknown/Zone')).toBeNull()
})
