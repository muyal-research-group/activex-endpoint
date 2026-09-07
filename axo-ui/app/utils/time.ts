const RELATIVE_UNITS: Array<[Intl.RelativeTimeFormatUnit, number]> = [
  ['year', 31536000],
  ['month', 2592000],
  ['week', 604800],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
  ['second', 1],
]

export function formatRelativeTime(dateInput: string | Date, now: Date = new Date()): string {
  const date = typeof dateInput === 'string' ? new Date(dateInput) : dateInput
  const diffSeconds = (date.getTime() - now.getTime()) / 1000

  const [unit, secondsInUnit] = RELATIVE_UNITS.find(([, threshold]) => Math.abs(diffSeconds) >= threshold)
    ?? RELATIVE_UNITS[RELATIVE_UNITS.length - 1]!

  return new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' }).format(
    Math.round(diffSeconds / secondsInUnit),
    unit,
  )
}

export function formatAbsoluteMxTime(dateInput: string | Date): string {
  const date = typeof dateInput === 'string' ? new Date(dateInput) : dateInput

  return new Intl.DateTimeFormat(undefined, {
    timeZone: 'America/Mexico_City',
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZoneName: 'short',
  }).format(date)
}
