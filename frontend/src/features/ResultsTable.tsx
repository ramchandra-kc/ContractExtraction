import type { BestValue } from '@/api/client'
import { JsonValue } from '@/components/JsonValue'
import { VerdictBadge } from '@/components/VerdictBadge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'

/** The best value per field, as chosen by the API (v_best_values). */
export function ResultsTable({ best, onOpen }: { best: BestValue[]; onOpen: (fieldResultId: string) => void }) {
  if (best.length === 0) return <p className="text-sm text-muted-foreground">No results yet.</p>
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Field</TableHead>
          <TableHead>Value</TableHead>
          <TableHead>Verdict</TableHead>
          <TableHead>RAG config</TableHead>
          <TableHead>Explanation</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {best.map((b) => (
          <TableRow key={b.field_key} className="align-top">
            <TableCell className="font-medium">
              <button
                type="button"
                onClick={() => onOpen(b.field_result_id)}
                className="text-left underline-offset-4 hover:underline"
              >
                {b.field_label}
              </button>
            </TableCell>
            <TableCell className="max-w-md whitespace-normal">
              {b.status === 'extracted' ? (
                <JsonValue value={b.value} />
              ) : (
                <span className="text-muted-foreground">{b.status.replace('_', ' ')}</span>
              )}
            </TableCell>
            <TableCell>
              <VerdictBadge verdict={b.verdict} issue={b.issue} />
            </TableCell>
            <TableCell className="font-mono text-xs">{b.retrieval_config}</TableCell>
            <TableCell className="max-w-md text-xs whitespace-normal text-muted-foreground">{b.explanation}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  )
}
