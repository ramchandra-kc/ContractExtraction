import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const STATE_STYLE: Record<string, string> = {
  queued: 'bg-slate-100 text-slate-700',
  running: 'bg-blue-100 text-blue-800',
  succeeded: 'bg-emerald-100 text-emerald-800',
  failed: 'bg-red-100 text-red-800',
  cancelled: 'bg-amber-100 text-amber-800',
}

/** A run's state, with its stage while running. */
export function StateBadge({ state, stage }: { state: string; stage?: string | null }) {
  return (
    <Badge variant="outline" className={cn('border-transparent', STATE_STYLE[state])}>
      {state}
      {state === 'running' && stage ? ` · ${stage}` : ''}
    </Badge>
  )
}
