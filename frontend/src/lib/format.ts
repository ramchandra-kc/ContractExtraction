export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit++
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'medium' })
}

export function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString(undefined, { timeStyle: 'medium' })
}

export function formatMs(ms: number | null | undefined): string {
  if (ms == null) return '—'
  if (ms < 1000) return `${ms} ms`
  const s = ms / 1000
  if (s < 60) return `${s.toFixed(1)} s`
  const m = Math.floor(s / 60)
  return `${m} min ${Math.round(s % 60)} s`
}

/** Time between two timestamps; an unfinished span is measured up to now. */
export function formatSpan(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '—'
  return formatMs((end ? Date.parse(end) : Date.now()) - Date.parse(start))
}
