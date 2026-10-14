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
              <TableCell>
                <Badge variant="outline">{f.value_type}</Badge>
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
  const [userPrompt, setUserPrompt] = useState(initial?.user_prompt ?? '')
  const [enabled, setEnabled] = useState(initial?.is_enabled ?? true)
  const [queries, setQueries] = useState((initial?.queries ?? []).join('\n'))

  const body = {
    label: label.trim(),
    description: toText(description),
    value_type: valueType,
    user_prompt: userPrompt,
    is_enabled: enabled,
    queries: queries.split('\n').map((q) => q.trim()).filter(Boolean),
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
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput label="Label" value={label} onChange={setLabel} />
        <SelectInput
          label="Value type"
          value={valueType}
          onChange={(v) => setValueType(v as ValueType)}
          options={VALUE_TYPES.map((t) => ({ value: t, label: t }))}
        />
      </div>
      <TextInput label="Description" value={description} onChange={setDescription} />
      <TextInput
        label="Extraction prompt"
        value={userPrompt}
        onChange={setUserPrompt}
        rows={8}
        mono
        hint="The retrieved context is appended when a run executes."
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
        disabled={!label.trim() || !userPrompt.trim() || (!initial && !key.trim())}
        onSubmit={submit}
      />
    </div>
  )
}
