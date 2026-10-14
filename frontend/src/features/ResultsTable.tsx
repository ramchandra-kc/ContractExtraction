import { useState } from 'react'
import type { BestValue } from '@/api/client'
import { useGroundTruth, useSetGroundTruth } from '@/api/hooks'
import { JsonValue } from '@/components/JsonValue'
import { VerdictBadge } from '@/components/VerdictBadge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { LabelEditor, LabelValue } from '@/features/LabelEditor'
import { draftFromOutcome, toDraft } from '@/lib/groundTruth'

function Match({ match }: { match: boolean | null | undefined }) {
  if (match === true) return <span className="text-emerald-700" aria-label="matches">✓</span>
  if (match === false) return <span className="text-red-700" aria-label="does not match">✗</span>
  return <span className="text-muted-foreground" aria-label="not labelled">—</span>
}

/** The best value per field, as chosen by the API (v_best_values), next to the document's ground truth. */
export function ResultsTable({
  best,
  documentId,
  onOpen,
}: {
  best: BestValue[]
  documentId: string
  onOpen: (fieldResultId: string) => void
}) {
  const [labeling, setLabeling] = useState<BestValue | null>(null)
  if (best.length === 0) return <p className="text-sm text-muted-foreground">No results yet.</p>
  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Field</TableHead>
            <TableHead>Value</TableHead>
            <TableHead>Verdict</TableHead>
            <TableHead>Expected</TableHead>
            <TableHead>Match</TableHead>
            <TableHead>RAG config</TableHead>
            <TableHead>Explanation</TableHead>
            <TableHead />
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
              <TableCell className="max-w-xs whitespace-normal">
                <LabelValue value={b.expected_value} />
              </TableCell>
              <TableCell className="text-center">
                <Match match={b.exact_match} />
              </TableCell>
              <TableCell className="font-mono text-xs">{b.retrieval_config}</TableCell>
              <TableCell className="max-w-md text-xs whitespace-normal text-muted-foreground">{b.explanation}</TableCell>
              <TableCell>
                <Button size="sm" variant="outline" onClick={() => setLabeling(b)} aria-label={`Label ${b.field_label}`}>
                  Label…
                </Button>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      {labeling && <LabelDialog key={labeling.field_id} best={labeling} documentId={documentId} onClose={() => setLabeling(null)} />}
    </>
  )
}

/** Label a field from a run: starts from the current label, or from the run's best value. */
function LabelDialog({ best, documentId, onClose }: { best: BestValue; documentId: string; onClose: () => void }) {
  const setLabel = useSetGroundTruth(documentId)
  // Notes are not part of run results; read them so saving keeps them.
  const labels = useGroundTruth(documentId)
  const notes = labels.data?.items.find((i) => i.field_id === best.field_id)?.notes
  const labelled = best.expected_value !== null && best.expected_value !== undefined
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Ground truth: {best.field_label}</DialogTitle>
          <DialogDescription>
            {labelled ? 'Edit the expected value for this document.' : 'Starts from the best value of this run.'}
          </DialogDescription>
        </DialogHeader>
        {labels.isPending ? (
          <Skeleton className="h-32" />
        ) : (
          <LabelEditor
            valueType={best.value_type}
            initial={
              labelled
                ? toDraft(best.expected_value, best.value_type)
                : draftFromOutcome(best.status, best.value, best.value_type)
            }
            initialNotes={notes}
            pending={setLabel.isPending}
            error={setLabel.error}
            onCancel={onClose}
            onSave={(value, notes) => setLabel.mutate({ fieldId: best.field_id, value, notes }, { onSuccess: onClose })}
          />
        )}
      </DialogContent>
    </Dialog>
  )
}
