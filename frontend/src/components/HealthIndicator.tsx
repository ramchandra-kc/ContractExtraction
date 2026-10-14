import { useHealth } from '@/api/hooks'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { cn } from '@/lib/utils'

/** Readiness of the backend's services (database, pipeline, Qdrant, model endpoints). */
export function HealthIndicator() {
  const { data, isPending } = useHealth()
  const ok = data?.status === 'ok'
  const label = isPending ? 'checking…' : ok ? 'ready' : 'degraded'
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className="flex items-center gap-2 text-sm text-muted-foreground" aria-label={`Services ${label}`}>
          <span className={cn('size-2 rounded-full', isPending ? 'bg-slate-300' : ok ? 'bg-emerald-500' : 'bg-red-500')} />
          {label}
        </span>
      </TooltipTrigger>
      <TooltipContent align="end">
        <ul className="space-y-1">
          {data?.components.map((c) => (
            <li key={c.name}>
              {c.ok ? '✓' : '✗'} <strong>{c.name}</strong>
              {c.detail ? `: ${c.detail}` : ''}
            </li>
          ))}
        </ul>
      </TooltipContent>
    </Tooltip>
  )
}
