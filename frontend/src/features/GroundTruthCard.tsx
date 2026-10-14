import { Fragment, useState } from 'react'
import { useDeleteGroundTruth, useGroundTruth, useSetGroundTruth } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { LabelEditor, LabelValue } from '@/features/LabelEditor'
import { formatDateTime } from '@/lib/format'
import { toDraft } from '@/lib/groundTruth'

/** Expected values for a document, one row per field of the default pipeline's field set. */
export function GroundTruthCard({ documentId }: { documentId: string }) {
  const labels = useGroundTruth(documentId)
  const setLabel = useSetGroundTruth(documentId)
  const clearLabel = useDeleteGroundTruth(documentId)
  const [editing, setEditing] = useState<string | null>(null)

  const edit = (fieldId: string | null) => {
    setLabel.reset()
    setEditing(fieldId)
  }

  const data = labels.data
  const labelled = data?.items.filter((i) => i.expected_value !== null && i.expected_value !== undefined).length ?? 0
  return (
    <Card>
      <CardHeader>
        <CardTitle>Ground truth</CardTitle>
        {data && (
          <CardDescription>
            {data.field_set.name} v{data.field_set.version} · {labelled} of {data.items.length} fields labelled. Run
            results compare their best values with these labels.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <ProblemAlert error={labels.error ?? clearLabel.error} />
        {labels.isPending && <Skeleton className="h-24" />}
        {data && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Field</TableHead>
                <TableHead>Expected value</TableHead>
                <TableHead>Notes</TableHead>
                <TableHead>Updated</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.items.map((item) => (
                <Fragment key={item.field_id}>
                  <TableRow className="align-top">
                    <TableCell className="font-medium">
                      {item.field_label}
                      <span className="ml-2 text-xs font-normal text-muted-foreground">{item.value_type}</span>
                    </TableCell>
                    <TableCell className="max-w-md whitespace-normal">
                      <LabelValue value={item.expected_value} />
                    </TableCell>
                    <TableCell className="max-w-xs text-xs whitespace-normal text-muted-foreground">{item.notes}</TableCell>
                    <TableCell className="text-xs text-muted-foreground">
                      {item.updated_at ? formatDateTime(item.updated_at) : ''}
                    </TableCell>
                    <TableCell className="space-x-1 text-right">
                      <Button size="sm" variant="outline" onClick={() => edit(item.field_id)} aria-label={`Edit ${item.field_label}`}>
                        Edit
                      </Button>
                      {item.updated_at && (
                        <Button
                          size="sm"
                          variant="ghost"
                          disabled={clearLabel.isPending}
                          onClick={() => clearLabel.mutate(item.field_id)}
                          aria-label={`Clear ${item.field_label}`}
                        >
                          Clear
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {editing === item.field_id && (
                    <TableRow>
                      <TableCell colSpan={5} className="bg-muted/40 whitespace-normal">
                        <LabelEditor
                          valueType={item.value_type}
                          initial={toDraft(item.expected_value, item.value_type)}
                          initialNotes={item.notes}
                          pending={setLabel.isPending}
                          error={setLabel.error}
                          onCancel={() => edit(null)}
                          onSave={(value, notes) =>
                            setLabel.mutate({ fieldId: item.field_id, value, notes }, { onSuccess: () => edit(null) })
                          }
                        />
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  )
}
