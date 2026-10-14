import type { EventOut } from '@/api/client'
import { formatTime } from '@/lib/format'
import { cn } from '@/lib/utils'

const LEVEL_STYLE: Record<string, string> = {
  debug: 'text-slate-500',
  info: 'text-slate-700',
  warning: 'text-amber-700',
  error: 'text-red-700',
}

/** The run's timeline (run_events), oldest first. */
export function EventsTimeline({ events }: { events: EventOut[] }) {
  if (events.length === 0) return <p className="text-sm text-muted-foreground">No events yet.</p>
  return (
    <ol className="space-y-1 font-mono text-xs">
      {events.map((e) => (
        <li key={e.id} className={cn('grid grid-cols-[6rem_4rem_6rem_1fr] gap-2', LEVEL_STYLE[e.level])}>
          <span className="text-muted-foreground">{formatTime(e.created_at)}</span>
          <span>{e.level}</span>
          <span>{e.stage ?? ''}</span>
          <span className="whitespace-pre-wrap">
            {e.message}
            {Object.keys(e.data).length > 0 && (
              <details>
                <summary className="cursor-pointer text-muted-foreground">data</summary>
                <pre className="whitespace-pre-wrap">{JSON.stringify(e.data, null, 2)}</pre>
              </details>
            )}
          </span>
        </li>
      ))}
    </ol>
  )
}
