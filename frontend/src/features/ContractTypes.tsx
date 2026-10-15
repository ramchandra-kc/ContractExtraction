import type { RunOut } from '@/api/client'
import { Badge } from '@/components/ui/badge'

const SOURCE: Record<string, string> = {
  classifier: 'detected',
  override: 'set for this run',
  fallback: 'fallback',
}

/** The contract types a run used (selected) and the other proposals of the classifier. */
export function ContractTypes({ types }: { types: RunOut['contract_types'] }) {
  if (!types?.length) return null
  const used = types.filter((t) => t.selected)
  const others = types.filter((t) => !t.selected)
  return (
    <section aria-label="Contract type" className="space-y-2 rounded-md border p-3">
      <h2 className="text-sm font-medium">Contract type</h2>
      <ul className="space-y-1">
        {used.map((t) => (
          <li key={t.key} className="text-sm">
            <span className="flex flex-wrap items-center gap-2">
              <Badge>{t.label}</Badge>
              <span className="text-xs text-muted-foreground">
                {SOURCE[t.source] ?? t.source}
                {t.confidence != null && ` · confidence ${Number(t.confidence).toFixed(2)}`}
              </span>
            </span>
            {t.evidence && <q className="mt-1 block text-xs text-muted-foreground italic">{t.evidence}</q>}
          </li>
        ))}
      </ul>
      {others.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Also proposed (below the confidence threshold):{' '}
          {others.map((t) => `${t.label}${t.confidence != null ? ` (${Number(t.confidence).toFixed(2)})` : ''}`).join(', ')}
        </p>
      )}
    </section>
  )
}
