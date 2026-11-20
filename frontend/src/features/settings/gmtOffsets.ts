const offsets = [...Array.from({ length: 27 }, (_, index) => (index - 12) * 60),
  -570, -210, -150, 210, 270, 330, 345, 390, 525, 570, 630, 765, 825].sort((a, b) => a - b)

export function gmtOffset(minutes: number) {
  const amount = Math.abs(minutes)
  return `GMT${minutes >= 0 ? '+' : '-'}${String(Math.floor(amount / 60)).padStart(2, '0')}:${String(amount % 60).padStart(2, '0')}`
}

export const GMT_ZONES = offsets.map(gmtOffset)

export function gmtLabel(zone: string) {
  const match = /^GMT([+-])(\d{2}):(\d{2})$/.exec(zone)
  return match ? `GMT${match[1]}${Number(match[2])}${match[3] === '00' ? '' : ':' + match[3]}` : zone
}

/** Display a saved regional zone at its current offset without changing it until save. */
export function asGmtOffset(zone: string, date = new Date()): string | null {
  if (/^GMT[+-]\d{2}:\d{2}$/.test(zone)) return zone
  try {
    const value = new Intl.DateTimeFormat('en', { timeZone: zone, timeZoneName: 'longOffset' })
      .formatToParts(date).find(part => part.type === 'timeZoneName')?.value
    if (value === 'GMT' || value === 'UTC') return gmtOffset(0)
    const match = /^GMT([+-])(\d{1,2}):(\d{2})$/.exec(value || '')
    return match ? gmtOffset((Number(match[2]) * 60 + Number(match[3])) * (match[1] === '+' ? 1 : -1)) : null
  } catch {
    return null
  }
}
