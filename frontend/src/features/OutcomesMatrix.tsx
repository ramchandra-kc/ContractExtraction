import type { FieldResultOut } from '@/api/client'
import { VerdictBadge } from '@/components/VerdictBadge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

function preview(value: unknown): string {
  if (value === null || value === undefined) return '—'
  const text = typeof value === 'string' ? value : JSON.stringify(value)
  return text.length > 80 ? `${text.slice(0, 79)}…` : text
}

/**
 * Every outcome: one row per field, one column per RAG config. The API returns results in priority order,
 * so first appearance gives the column and row order.
 */
export function OutcomesMatrix({ results, onOpen }: { results: FieldResultOut[]; onOpen: (fieldResultId: string) => void }) {
  if (results.length === 0) return <p className="text-sm text-muted-foreground">No outcomes yet.</p>

  const configs = [...new Set(results.map((r) => r.retrieval_config))]
  const fields = new Map<string, string>()
  const cells = new Map<string, FieldResultOut>()
  for (const r of results) {
    if (!fields.has(r.field_key)) fields.set(r.field_key, r.field_label)
    cells.set(`${r.field_key}|${r.retrieval_config}`, r)
  }

  return (
    <div className="overflow-x-auto">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead className="sticky left-0 bg-background">Field</TableHead>
            {configs.map((c) => (
              <TableHead key={c} className="font-mono">
                {c}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...fields].map(([key, label]) => (
            <TableRow key={key} className="align-top">
              <TableCell className="sticky left-0 bg-background font-medium">{label}</TableCell>
              {configs.map((c) => {
                const r = cells.get(`${key}|${c}`)
                return (
                  <TableCell key={c} className="min-w-40 whitespace-normal">
                    {r ? (
                      <button
                        type="button"
                        onClick={() => onOpen(r.id)}
                        className="flex w-full flex-col items-start gap-1 rounded p-1 text-left hover:bg-accent"
                        aria-label={`${label} with ${c}`}
                      >
                        <span className={r.status === 'extracted' ? 'text-sm' : 'text-sm text-muted-foreground'}>
                          {r.status === 'extracted' ? preview(r.value) : r.status.replace('_', ' ')}
                        </span>
                        <VerdictBadge verdict={r.verdict} issue={r.issue} />
                      </button>
                    ) : (
                      <span className="text-muted-foreground">·</span>
                    )}
                  </TableCell>
                )
              })}
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}
