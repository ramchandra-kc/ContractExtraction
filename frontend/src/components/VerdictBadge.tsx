import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'

const VERDICT_STYLE: Record<string, string> = {
  PASS: 'bg-emerald-100 text-emerald-800',
  FAIL: 'bg-red-100 text-red-800',
  ERROR: 'bg-amber-100 text-amber-800',
  SKIPPED: 'bg-slate-100 text-slate-600',
}

/** The judge's verdict; a dash when the result was not judged. */
export function VerdictBadge({ verdict, issue }: { verdict: string | null | undefined; issue?: string | null }) {
  if (!verdict) return <span className="text-muted-foreground">—</span>
  return (
    <Badge variant="outline" className={cn('border-transparent', VERDICT_STYLE[verdict])} title={issue ?? undefined}>
      {verdict}
      {issue && issue !== 'NONE' ? ` · ${issue}` : ''}
    </Badge>
  )
}
