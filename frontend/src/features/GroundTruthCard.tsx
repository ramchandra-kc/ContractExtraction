import { Fragment, useId, useState } from 'react'
import { useDeleteGroundTruth, useGroundTruth, useSetContractTypes, useSetGroundTruth } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { LabelEditor, LabelValue } from '@/features/LabelEditor'
import { formatDateTime } from '@/lib/format'
import { editorKind, toDraft } from '@/lib/groundTruth'

const isLabelled = (value: unknown) => value !== null && value !== undefined
const PRIORITIES = ['P1', 'P2', 'P3'] as const

/**
 * Expected values for a document: its contract type(s), and one row per field of the default pipeline's
 * field set. Once the types are labelled, only their fields (and fields already labelled) are listed.
 */
export function GroundTruthCard({ documentId }: { documentId: string }) {
  const switchId = useId()
  const labels = useGroundTruth(documentId)
  const setLabel = useSetGroundTruth(documentId)
  const clearLabel = useDeleteGroundTruth(documentId)
  const setTypes = useSetContractTypes(documentId)
  const [editing, setEditing] = useState<string | null>(null)
  const [showAll, setShowAll] = useState(false)
  const [shown, setShown] = useState<string[]>([...PRIORITIES])

  const edit = (fieldId: string | null) => {
    setLabel.reset()
    setEditing(fieldId)
  }

  const data = labels.data
  const expected = data?.expected_contract_types ?? []
  const typeFields = new Set((data?.contract_types ?? []).filter((t) => expected.includes(t.key)).flatMap((t) => t.field_keys))
  const filtered = expected.length > 0 && !showAll
  const typed = data?.items.filter((i) => !filtered || typeFields.has(i.field_key) || isLabelled(i.expected_value)) ?? []
  const items = typed.filter((i) => shown.includes(i.priority))
  const labelled = data?.items.filter((i) => isLabelled(i.expected_value)).length ?? 0
  const toggleType = (key: string) =>
    setTypes.mutate(expected.includes(key) ? expected.filter((k) => k !== key) : [...expected, key])
  const togglePriority = (p: string) => setShown(shown.includes(p) ? shown.filter((s) => s !== p) : [...shown, p])

  return (
    <Card>
      <CardHeader>
        <CardTitle>Ground truth</CardTitle>
        {data && (
          <CardDescription>
            {data.field_set.name} v{data.field_set.version} · {labelled} of {data.items.length} fields labelled. Run
            results compare their contract types and best values with these labels.
          </CardDescription>
        )}
      </CardHeader>
      <CardContent className="space-y-3">
        <ProblemAlert error={labels.error ?? clearLabel.error ?? setTypes.error} />
        {labels.isPending && <Skeleton className="h-24" />}
        {data && data.contract_types.length > 0 && (
          <section aria-label="Contract type labels" className="space-y-2">
            <p className="text-sm font-medium">
              Contract type{' '}
              <span className="font-normal text-muted-foreground">
                {expected.length ? '' : '— not labelled; choose the type(s) this document is'}
              </span>
            </p>
            <div className="flex flex-wrap gap-1">
              {data.contract_types
                .filter((t) => !t.is_fallback)
                .map((t) => (
                  <Button
                    key={t.key}
                    size="sm"
                    variant={expected.includes(t.key) ? 'default' : 'outline'}
                    aria-pressed={expected.includes(t.key)}
                    disabled={setTypes.isPending}
                    title={t.description}
                    onClick={() => toggleType(t.key)}
                  >
                    {t.label}
                  </Button>
                ))}
            </div>
            {expected.length > 0 && (
              <div className="flex items-center gap-3">
                <Switch id={switchId} checked={showAll} onCheckedChange={setShowAll} />
                <Label htmlFor={switchId} className="font-normal">
                  Show all {data.items.length} fields (otherwise this type&apos;s {typeFields.size} and those already labelled)
                </Label>
              </div>
            )}
          </section>
        )}
        {data && (
          <section aria-label="Field priorities" className="flex flex-wrap items-center gap-1">
            <p className="mr-2 text-sm font-medium">Priority</p>
            {PRIORITIES.map((p) => (
              <Button
                key={p}
                size="sm"
                variant={shown.includes(p) ? 'default' : 'outline'}
                aria-pressed={shown.includes(p)}
                title={`${shown.includes(p) ? 'Hide' : 'Show'} ${p} fields`}
                onClick={() => togglePriority(p)}
              >
                {p} ({typed.filter((i) => i.priority === p).length})
              </Button>
            ))}
          </section>
        )}
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
              {items.map((item) => (
                <Fragment key={item.field_id}>
                  <TableRow className="align-top">
                    <TableCell className="font-medium whitespace-normal">
                      {item.field_label}
                      <Badge variant={item.priority === 'P1' ? 'secondary' : 'outline'} className="ml-2">
                        {item.priority}
                      </Badge>
                      <span className="ml-2 font-mono text-xs font-normal text-muted-foreground">
                        {item.type_spec ?? item.value_type}
                      </span>
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
                          valueSchema={item.value_schema}
                          initial={toDraft(item.expected_value, editorKind(item.value_type, item.value_schema))}
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
