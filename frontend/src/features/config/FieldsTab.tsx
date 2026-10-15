import { useState } from 'react'
import { configApi, useConfigWrite, type Catalog, type CatalogField, type CatalogFieldSet } from '@/api/config'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toText } from '@/lib/formValues'
import { FormDialog, SelectInput, SubmitBar, SwitchInput, TextInput } from './form'

const VALUE_TYPES = ['text', 'date', 'number', 'money', 'list', 'boolean', 'json'] as const
type ValueType = (typeof VALUE_TYPES)[number]
const PRIORITIES = ['P1', 'P2', 'P3'] as const
type Priority = (typeof PRIORITIES)[number]
// 'none' stands for no anchor (a select item cannot have an empty value).
const ANCHORS = [
  { value: 'none', label: 'None' },
  { value: 'start', label: 'Opening chunks' },
  { value: 'end', label: 'Closing chunks' },
  { value: 'both', label: 'Opening and closing' },
] as const
type Anchor = 'start' | 'end' | 'both'

export function FieldsTab({ catalog }: { catalog: Catalog }) {
  const [selected, setSelected] = useState(0)
  const fieldSet = catalog.field_sets[selected]
  const toggle = useConfigWrite(configApi.updateField)
  if (!fieldSet) return <p className="text-sm text-muted-foreground">No field sets.</p>
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        {catalog.field_sets.length > 1 ? (
          <div className="w-64">
            <SelectInput
              label="Field set"
              value={String(selected)}
              onChange={(v) => setSelected(Number(v))}
              options={catalog.field_sets.map((f, i) => ({ value: String(i), label: `${f.name} v${f.version}` }))}
            />
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            {fieldSet.name} v{fieldSet.version} · edits apply to runs queued afterwards; disable a field instead of deleting it.
          </p>
        )}
        <FormDialog title={`New field in ${fieldSet.name} v${fieldSet.version}`} wide trigger={<Button>New field</Button>}>
          {(close) => <FieldForm fieldSet={fieldSet} onDone={close} />}
        </FormDialog>
      </div>
      <ProblemAlert error={toggle.error} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>#</TableHead>
            <TableHead>Field</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Expansion queries</TableHead>
            <TableHead>Enabled</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {fieldSet.fields.map((f) => (
            <TableRow key={f.id} className="align-top">
              <TableCell className="text-muted-foreground">{f.position}</TableCell>
              <TableCell className="whitespace-normal">
                <span className="font-medium">{f.label}</span> <span className="font-mono text-xs text-muted-foreground">{f.key}</span>
                {f.description && <p className="text-xs text-muted-foreground">{f.description}</p>}
              </TableCell>
              <TableCell className="whitespace-normal">
                <div className="flex gap-1">
                  <Badge variant="outline">{f.value_type}</Badge>
                  <Badge variant={f.priority === 'P1' ? 'default' : 'secondary'}>{f.priority}</Badge>
                  {f.anchor && (
                    <Badge variant="outline" title="Evidence always includes these chunks when the RAG config sets anchor chunks">
                      anchor: {f.anchor}
                    </Badge>
                  )}
                </div>
                {f.type_spec && <p className="mt-1 max-w-48 font-mono text-xs text-muted-foreground">{f.type_spec}</p>}
              </TableCell>
              <TableCell className="max-w-md text-xs whitespace-normal text-muted-foreground">{f.queries.join(' · ')}</TableCell>
              <TableCell>
                <Switch
                  checked={f.is_enabled}
                  disabled={toggle.isPending}
                  onCheckedChange={(on) => toggle.mutate({ id: f.id, body: { is_enabled: on } })}
                  aria-label={`${f.label} enabled`}
                />
              </TableCell>
              <TableCell className="text-right">
                <FormDialog
                  title={`Edit field ${f.label}`}
                  wide
                  trigger={
                    <Button size="sm" variant="outline" aria-label={`Edit ${f.label}`}>
                      Edit
                    </Button>
                  }
                >
                  {(close) => <FieldForm fieldSet={fieldSet} initial={f} onDone={close} />}
                </FormDialog>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function FieldForm({ fieldSet, initial, onDone }: { fieldSet: CatalogFieldSet; initial?: CatalogField; onDone: () => void }) {
  const create = useConfigWrite(configApi.createField)
  const update = useConfigWrite(configApi.updateField)
  const write = initial ? update : create
  const [key, setKey] = useState('')
  const [label, setLabel] = useState(initial?.label ?? '')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [valueType, setValueType] = useState<ValueType>((initial?.value_type as ValueType) ?? 'text')
  const [priority, setPriority] = useState<Priority>(initial?.priority ?? 'P2')
  const [userPrompt, setUserPrompt] = useState(initial?.user_prompt ?? '')
  const [enabled, setEnabled] = useState(initial?.is_enabled ?? true)
  const [queries, setQueries] = useState((initial?.queries ?? []).join('\n'))
  const [anchor, setAnchor] = useState<string>(initial?.anchor ?? 'none')

  const body = {
    label: label.trim(),
    description: toText(description),
    value_type: valueType,
    priority,
    user_prompt: toText(userPrompt),
    is_enabled: enabled,
    queries: queries.split('\n').map((q) => q.trim()).filter(Boolean),
    anchor: anchor === 'none' ? null : (anchor as Anchor),
  }
  const submit = () => {
    if (initial) update.mutate({ id: initial.id, body }, { onSuccess: onDone })
    else create.mutate({ fieldSet: { name: fieldSet.name, version: fieldSet.version }, body: { key: key.trim(), ...body } }, { onSuccess: onDone })
  }
  return (
    <div className="space-y-3">
      {!initial && (
        <TextInput label="Key" value={key} onChange={setKey} placeholder="notice_period" hint="Lowercase letters, digits and _. Cannot be changed later." />
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <TextInput label="Label" value={label} onChange={setLabel} />
        <SelectInput
          label="Value type"
          value={valueType}
          onChange={(v) => setValueType(v as ValueType)}
          options={VALUE_TYPES.map((t) => ({ value: t, label: t }))}
        />
        <SelectInput
          label="Priority"
          value={priority}
          onChange={(v) => setPriority(v as Priority)}
          options={PRIORITIES.map((p) => ({ value: p, label: p }))}
        />
      </div>
      <TextInput label="Description" value={description} onChange={setDescription} />
      <SelectInput label="Anchor" value={anchor} onChange={setAnchor} options={ANCHORS.map((a) => ({ ...a }))} />
      <TextInput
        label="Extraction prompt (optional)"
        value={userPrompt}
        onChange={setUserPrompt}
        rows={8}
        mono
        hint="Leave empty to use the generic prompt built from the description and value type. The retrieved context is appended when a run executes."
      />
      <TextInput
        label="Expansion queries"
        value={queries}
        onChange={setQueries}
        rows={5}
        hint="One per line. Used by RAG configs with query expansion on."
      />
      <SwitchInput label="Enabled" checked={enabled} onChange={setEnabled} />
      <SubmitBar
        label={initial ? 'Save field' : 'Add field'}
        pending={write.isPending}
        error={write.error}
        disabled={!label.trim() || (!initial && !key.trim())}
        onSubmit={submit}
      />
    </div>
  )
}
