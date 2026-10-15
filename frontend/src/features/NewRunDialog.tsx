import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { ProblemError, type DocumentDetail, type PipelineOut, type RunCreate } from '@/api/client'
import { isActive, useCreateRun, usePipelines } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'

type Kind = NonNullable<RunCreate['kind']>

const KINDS: { value: Kind; label: string }[] = [
  { value: 'full', label: 'Full (decompose, index, extract)' },
  { value: 'decompose', label: 'Decompose only' },
  { value: 'extract', label: 'Extract (reuse decomposition and index)' },
]

/** Queue a run for a document, optionally narrowed to some fields and RAG configs. */
export function NewRunDialog({ document }: { document: DocumentDetail }) {
  const [open, setOpen] = useState(false)
  const active = isActive(document.latest_run?.state)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button disabled={active} title={active ? 'This document already has an active run' : undefined}>
          New run
        </Button>
      </DialogTrigger>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>New run for {document.code}</DialogTitle>
          <DialogDescription>The run is queued and a worker executes it.</DialogDescription>
        </DialogHeader>
        {open && <RunForm document={document} />}
      </DialogContent>
    </Dialog>
  )
}

function RunForm({ document }: { document: DocumentDetail }) {
  const pipelines = usePipelines()
  const [name, setName] = useState<string | null>(null)
  const selected = pipelines.data?.find((p) => p.name === name) ?? pipelines.data?.find((p) => p.is_default && !p.error)

  if (pipelines.isPending) return <Skeleton className="h-40" />
  if (pipelines.error) return <ProblemAlert error={pipelines.error} />
  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Label htmlFor="pipeline">Pipeline</Label>
        <Select value={selected?.name} onValueChange={setName}>
          <SelectTrigger id="pipeline" className="w-full">
            <SelectValue placeholder="Choose a pipeline" />
          </SelectTrigger>
          <SelectContent>
            {pipelines.data.map((p) => (
              <SelectItem key={p.name} value={p.name} disabled={!!p.error}>
                {p.name}
                {p.is_default ? ' (default)' : ''}
                {p.error ? ` — ${p.error}` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {selected?.description && <p className="text-xs text-muted-foreground">{selected.description}</p>}
      </div>
      {/* Remount per pipeline so the selections start from that pipeline's fields and RAG configs. */}
      {selected && <PipelineOptions key={selected.name} document={document} pipeline={selected} />}
    </div>
  )
}

type Scope = 'detect' | 'types' | 'fields'

function PipelineOptions({ document, pipeline }: { document: DocumentDetail; pipeline: PipelineOut }) {
  const navigate = useNavigate()
  const createRun = useCreateRun(document.id)
  const [kind, setKind] = useState<Kind>('full')
  const [scope, setScope] = useState<Scope>('detect')
  const [types, setTypes] = useState(() => new Set<string>())
  const [fields, setFields] = useState(() => new Set<string>())
  const [retrievals, setRetrievals] = useState(() => new Set(pipeline.retrievals?.map((r) => r.name)))
  const [judge, setJudge] = useState(!!pipeline.judge)
  const [reuseCalls, setReuseCalls] = useState(true)
  const [redecompose, setRedecompose] = useState(false)

  const allFields = pipeline.fields ?? []
  const allTypes = pipeline.contract_types ?? []
  const allRetrievals = pipeline.retrievals ?? []
  const fallback = allTypes.find((t) => t.is_fallback)
  const extracts = kind !== 'decompose'
  const chosen = scope === 'types' ? types.size > 0 : scope === 'fields' ? fields.size > 0 : true
  const valid = !extracts || (chosen && retrievals.size > 0)

  const scopes: { value: Scope; label: string; hint: string }[] = [
    allTypes.length === 0
      ? { value: 'detect', label: 'All fields', hint: 'Every field of the pipeline.' }
      : pipeline.classification_enabled
        ? { value: 'detect', label: 'Detect the contract type', hint: 'Extract the fields of the detected type(s).' }
        : { value: 'detect', label: `Fallback type (${fallback?.label ?? 'none'})`, hint: 'This pipeline does not detect types.' },
    ...(allTypes.length ? [{ value: 'types' as const, label: 'Contract types…', hint: 'Skip detection: extract these types’ fields.' }] : []),
    { value: 'fields', label: 'Fields…', hint: 'Extract exactly these fields.' },
  ]

  const submit = () => {
    const body: RunCreate = {
      pipeline: pipeline.name,
      kind,
      // null means "decided by the pipeline", which keeps the stored options short.
      fields: extracts && scope === 'fields' ? allFields.filter((f) => fields.has(f.key)).map((f) => f.key) : null,
      contract_types: extracts && scope === 'types' ? allTypes.filter((t) => types.has(t.key)).map((t) => t.key) : null,
      retrievals:
        extracts && retrievals.size < allRetrievals.length
          ? allRetrievals.filter((r) => retrievals.has(r.name)).map((r) => r.name)
          : null,
      judge: pipeline.judge && !judge ? false : null,
      reuse_calls: reuseCalls,
      redecompose,
    }
    createRun.mutate(body, { onSuccess: (run) => navigate(`/runs/${run.id}`) })
  }

  const conflict = createRun.error instanceof ProblemError && createRun.error.status === 409
  return (
    <>
      <div className="space-y-2">
        <Label htmlFor="kind">Kind</Label>
        <Select value={kind} onValueChange={(v) => setKind(v as Kind)}>
          <SelectTrigger id="kind" className="w-full">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {KINDS.map((k) => (
              <SelectItem key={k.value} value={k.value}>
                {k.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {extracts && (
        <>
          <fieldset className="space-y-2">
            <legend className="text-sm font-medium">What to extract</legend>
            {scopes.map((s) => (
              <label key={s.value} className="flex items-start gap-2 text-sm">
                <input
                  type="radio"
                  name="scope"
                  value={s.value}
                  checked={scope === s.value}
                  onChange={() => setScope(s.value)}
                  className="mt-1"
                />
                <span>
                  {s.label} <span className="text-muted-foreground">— {s.hint}</span>
                </span>
              </label>
            ))}
          </fieldset>
          {scope === 'types' && (
            <CheckList
              title="Contract types"
              items={allTypes.map((t) => ({ key: t.key, label: `${t.label} (${t.field_keys.length})`, hint: t.description }))}
              selected={types}
              onChange={setTypes}
            />
          )}
          {scope === 'fields' && (
            <CheckList
              title="Fields"
              items={allFields.map((f) => ({ key: f.key, label: f.label, hint: f.description ?? undefined }))}
              selected={fields}
              onChange={setFields}
            />
          )}
          <CheckList
            title="RAG configs (priority order)"
            items={allRetrievals.map((r) => ({
              key: r.name,
              label: r.name,
              hint: `top ${r.top_k}, threshold ${r.score_threshold}${r.query_expansion ? ', query expansion' : ''}`,
            }))}
            selected={retrievals}
            onChange={setRetrievals}
          />
        </>
      )}

      <div className="space-y-3">
        {extracts && (
          <Toggle
            id="judge"
            label={pipeline.judge ? `Judge with ${pipeline.judge.model}` : 'Judge (disabled in this pipeline)'}
            checked={judge}
            onChange={setJudge}
            disabled={!pipeline.judge}
          />
        )}
        {extracts && (
          <Toggle id="reuse" label="Reuse answers when the evidence repeats" checked={reuseCalls} onChange={setReuseCalls} />
        )}
        <Toggle id="redecompose" label="Decompose again" checked={redecompose} onChange={setRedecompose} />
      </div>

      <ProblemAlert error={createRun.error}>
        {conflict && document.latest_run && isActive(document.latest_run.state) && (
          <p>
            <Link to={`/runs/${document.latest_run.id}`} className="underline">
              Open the active run
            </Link>
          </p>
        )}
      </ProblemAlert>

      <DialogFooter>
        <Button onClick={submit} disabled={!valid || createRun.isPending}>
          {createRun.isPending ? 'Queueing…' : 'Queue run'}
        </Button>
      </DialogFooter>
    </>
  )
}

function CheckList({
  title,
  items,
  selected,
  onChange,
}: {
  title: string
  items: { key: string; label: string; hint?: string }[]
  selected: Set<string>
  onChange: (s: Set<string>) => void
}) {
  const all = selected.size === items.length
  const toggle = (key: string, on: boolean) => {
    const next = new Set(selected)
    if (on) next.add(key)
    else next.delete(key)
    onChange(next)
  }
  return (
    <fieldset className="space-y-2">
      <div className="flex items-center justify-between">
        <legend className="text-sm font-medium">
          {title} ({selected.size}/{items.length})
        </legend>
        <Button
          type="button"
          variant="link"
          size="sm"
          className="h-auto p-0"
          onClick={() => onChange(new Set(all ? [] : items.map((i) => i.key)))}
        >
          {all ? 'None' : 'All'}
        </Button>
      </div>
      <div className="grid max-h-48 grid-cols-1 gap-2 overflow-y-auto rounded-md border p-2 sm:grid-cols-2">
        {items.map((i) => (
          <label key={i.key} className="flex items-start gap-2 text-sm" title={i.hint}>
            <Checkbox checked={selected.has(i.key)} onCheckedChange={(v) => toggle(i.key, v === true)} className="mt-0.5" />
            <span>{i.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function Toggle({
  id,
  label,
  checked,
  onChange,
  disabled,
}: {
  id: string
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  return (
    <div className="flex items-center gap-3">
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
      <Label htmlFor={id} className="font-normal">
        {label}
      </Label>
    </div>
  )
}
