import { useState } from 'react'
import { ArrowDown, ArrowUp, X } from 'lucide-react'
import { configApi, useConfigWrite, type Catalog, type CatalogPipeline, type VersionRef } from '@/api/config'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toText } from '@/lib/formValues'
import { DeleteButton, FormDialog, SelectInput, SubmitBar, SwitchInput, TextInput } from './form'

const refKey = (r: VersionRef | null | undefined) => (r ? `${r.name}@${r.version}` : '')
const parseRef = (key: string): VersionRef | null => {
  const at = key.lastIndexOf('@')
  return at > 0 ? { name: key.slice(0, at), version: Number(key.slice(at + 1)) } : null
}

export function PipelinesTab({ catalog }: { catalog: Catalog }) {
  const setDefault = useConfigWrite(configApi.setDefaultPipeline)
  const remove = useConfigWrite(configApi.deletePipeline)
  const template = catalog.pipelines.find((p) => p.is_default) ?? catalog.pipelines[0]
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <FormDialog title="New pipeline" trigger={<Button>New pipeline</Button>} wide>
          {(close) => <PipelineForm catalog={catalog} initial={template} onDone={close} />}
        </FormDialog>
      </div>
      <ProblemAlert error={setDefault.error} />
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Pipeline</TableHead>
            <TableHead>Fields</TableHead>
            <TableHead>Extraction</TableHead>
            <TableHead>Judge</TableHead>
            <TableHead>RAG configs (priority order)</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {catalog.pipelines.map((p) => (
            <TableRow key={p.name} className="align-top">
              <TableCell className="whitespace-normal">
                <div className="flex items-center gap-2 font-medium">
                  {p.name}
                  {p.is_default && <Badge variant="secondary">default</Badge>}
                </div>
                {p.description && <p className="text-xs text-muted-foreground">{p.description}</p>}
                {p.error && <p className="text-xs text-red-700">Cannot run: {p.error}</p>}
              </TableCell>
              <TableCell className="text-xs">
                {p.field_set.name} v{p.field_set.version}
                <br />
                <span className="text-muted-foreground">
                  {p.classification_enabled ? `detect type (≥ ${p.classification_min_confidence})` : 'fallback type'}
                  {p.min_priority !== 'P3' && ` · ${p.min_priority === 'P1' ? 'P1 only' : 'P1–P2'}`}
                </span>
              </TableCell>
              <TableCell className="text-xs">
                {p.extraction_profile}
                <br />
                {p.extraction_prompt.name} v{p.extraction_prompt.version}
              </TableCell>
              <TableCell className="text-xs">
                {p.judge_enabled ? (
                  <>
                    {p.judge_profile}
                    <br />
                    {p.judge_prompt?.name} v{p.judge_prompt?.version}
                    {p.judge_parallel && ' · parallel'}
                  </>
                ) : (
                  <span className="text-muted-foreground">off</span>
                )}
              </TableCell>
              <TableCell className="font-mono text-xs whitespace-normal">{p.retrievals.join(' → ')}</TableCell>
              <TableCell className="space-x-1 text-right whitespace-nowrap">
                <FormDialog
                  title={`Edit pipeline ${p.name}`}
                  wide
                  trigger={
                    <Button size="sm" variant="outline" aria-label={`Edit ${p.name}`}>
                      Edit
                    </Button>
                  }
                >
                  {(close) => <PipelineForm catalog={catalog} initial={p} existing onDone={close} />}
                </FormDialog>
                {!p.is_default && (
                  <Button size="sm" variant="ghost" disabled={setDefault.isPending || !!p.error} onClick={() => setDefault.mutate(p.name)}>
                    Make default
                  </Button>
                )}
                {!p.is_default && (
                  <DeleteButton
                    name={p.name}
                    pending={remove.isPending && remove.variables === p.name}
                    error={remove.variables === p.name ? remove.error : null}
                    onDelete={() => remove.mutate(p.name)}
                  />
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function PipelineForm({
  catalog,
  initial,
  existing,
  onDone,
}: {
  catalog: Catalog
  initial: CatalogPipeline
  existing?: boolean
  onDone: () => void
}) {
  const create = useConfigWrite(configApi.createPipeline)
  const update = useConfigWrite(configApi.updatePipeline)
  const write = existing ? update : create

  const [name, setName] = useState(existing ? initial.name : '')
  const [description, setDescription] = useState(initial.description ?? '')
  const [decomposition, setDecomposition] = useState(initial.decomposition)
  const [index, setIndex] = useState(initial.index)
  const [fieldSet, setFieldSet] = useState(refKey(initial.field_set))
  const [extractionProfile, setExtractionProfile] = useState(initial.extraction_profile)
  const [extractionPrompt, setExtractionPrompt] = useState(refKey(initial.extraction_prompt))
  const [judgeEnabled, setJudgeEnabled] = useState(initial.judge_enabled)
  const [judgeProfile, setJudgeProfile] = useState(initial.judge_profile ?? '')
  const [judgePrompt, setJudgePrompt] = useState(refKey(initial.judge_prompt))
  const [judgeParallel, setJudgeParallel] = useState(initial.judge_parallel)
  const [classify, setClassify] = useState(initial.classification_enabled)
  const [classifyProfile, setClassifyProfile] = useState(initial.classification_profile ?? '')
  const [classifyPrompt, setClassifyPrompt] = useState(refKey(initial.classification_prompt))
  const [classifyPages, setClassifyPages] = useState(String(initial.classification_pages))
  const [minConfidence, setMinConfidence] = useState(String(initial.classification_min_confidence))
  const [minPriority, setMinPriority] = useState<CatalogPipeline['min_priority']>(initial.min_priority)
  const [granularity, setGranularity] = useState<CatalogPipeline['extraction_granularity']>(initial.extraction_granularity)
  const [groupMax, setGroupMax] = useState(String(initial.group_max_fields))
  const [retrievals, setRetrievals] = useState<string[]>(initial.retrievals)

  const prompts = (role: string) =>
    catalog.prompts
      .filter((p) => p.role === role)
      .map((p) => ({ value: refKey(p), label: `${p.name} v${p.version}${p.is_active ? ' (active)' : ''}` }))
  const profiles = catalog.profiles.map((p) => ({ value: p.name, label: `${p.name} — ${p.model}` }))
  const unused = catalog.retrievals.filter((r) => !retrievals.includes(r.name))

  const move = (i: number, by: number) => {
    const next = [...retrievals]
    ;[next[i], next[i + by]] = [next[i + by], next[i]]
    setRetrievals(next)
  }

  const body = {
    description: toText(description),
    decomposition,
    index,
    field_set: parseRef(fieldSet)!,
    extraction_profile: extractionProfile,
    extraction_prompt: parseRef(extractionPrompt)!,
    judge_enabled: judgeEnabled,
    judge_profile: judgeEnabled ? judgeProfile || null : null,
    judge_prompt: judgeEnabled ? parseRef(judgePrompt) : null,
    judge_parallel: judgeParallel,
    classification_enabled: classify,
    classification_profile: classify ? classifyProfile || null : null,
    classification_prompt: classify ? parseRef(classifyPrompt) : null,
    classification_pages: Number(classifyPages),
    classification_min_confidence: minConfidence.trim(),
    min_priority: minPriority,
    extraction_granularity: granularity,
    group_max_fields: Number(groupMax),
    retrievals,
  }
  const submit = () => {
    if (existing) update.mutate({ name: initial.name, body }, { onSuccess: onDone })
    else create.mutate({ name: name.trim(), ...body }, { onSuccess: onDone })
  }

  return (
    <div className="space-y-4">
      {!existing && <TextInput label="Name" value={name} onChange={setName} hint="Letters, digits, '.', '_' and '-'. Cannot be changed later." />}
      <TextInput label="Description" value={description} onChange={setDescription} />
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectInput
          label="Decomposition config"
          value={decomposition}
          onChange={setDecomposition}
          options={catalog.decompositions.map((d) => ({ value: d.name, label: `${d.name} (${d.method}, ${d.text_format})` }))}
        />
        <SelectInput
          label="Index config"
          value={index}
          onChange={setIndex}
          options={catalog.indexes.map((x) => ({ value: x.name, label: `${x.name} (${x.chunk_size}/${x.chunk_overlap}, ${x.embedding_model})` }))}
        />
        <SelectInput
          label="Field set"
          value={fieldSet}
          onChange={setFieldSet}
          options={catalog.field_sets.map((f) => ({ value: refKey(f), label: `${f.name} v${f.version}` }))}
        />
        <div />
        <SelectInput label="Extraction profile" value={extractionProfile} onChange={setExtractionProfile} options={profiles} />
        <SelectInput label="Extraction prompt" value={extractionPrompt} onChange={setExtractionPrompt} options={prompts('extraction_system')} />
      </div>

      <div className="space-y-3 rounded-md border p-3">
        <SwitchInput label="Detect the contract type first and extract only its fields" checked={classify} onChange={setClassify} />
        {classify ? (
          <div className="grid gap-3 sm:grid-cols-2">
            <SelectInput label="Classification profile" value={classifyProfile} onChange={setClassifyProfile} options={profiles} />
            <SelectInput label="Classification prompt" value={classifyPrompt} onChange={setClassifyPrompt} options={prompts('classification_system')} />
            <TextInput label="Pages read" value={classifyPages} onChange={setClassifyPages} hint="The classifier reads the document's first pages." />
            <TextInput
              label="Minimum confidence"
              value={minConfidence}
              onChange={setMinConfidence}
              hint="0–1. A type below this is not used; with none above it, the fallback type is."
            />
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">Runs extract the fallback type's fields unless a run names its contract type.</p>
        )}
        <SelectInput
          label="Fields to extract"
          value={minPriority}
          onChange={(v) => setMinPriority(v as CatalogPipeline['min_priority'])}
          options={[
            { value: 'P3', label: 'All of the contract type (P1–P3)' },
            { value: 'P2', label: 'P1 and P2 (skip informational)' },
            { value: 'P1', label: 'P1 only (financial, time or exit exposure)' },
          ]}
        />
        <div className="grid gap-3 sm:grid-cols-2">
          <SelectInput
            label="Extraction calls"
            value={granularity}
            onChange={(v) => setGranularity(v as CatalogPipeline['extraction_granularity'])}
            options={[
              { value: 'field', label: 'One per field (most precise)' },
              { value: 'group', label: 'One per field group (fewer calls)' },
            ]}
          />
          {granularity === 'group' && (
            <TextInput label="Fields per group call" value={groupMax} onChange={setGroupMax} hint="Larger groups are split." />
          )}
        </div>
      </div>

      <div className="space-y-3 rounded-md border p-3">
        <SwitchInput label="Judge every answer" checked={judgeEnabled} onChange={setJudgeEnabled} />
        {judgeEnabled && (
          <>
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectInput label="Judge profile" value={judgeProfile} onChange={setJudgeProfile} options={profiles} />
              <SelectInput label="Judge prompt" value={judgePrompt} onChange={setJudgePrompt} options={prompts('judge_system')} />
            </div>
            <SwitchInput label="Run judge calls in parallel with extraction" checked={judgeParallel} onChange={setJudgeParallel} />
          </>
        )}
      </div>

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">RAG configs, in priority order (the first one's answer is preferred)</legend>
        <ol className="space-y-1">
          {retrievals.map((r, i) => (
            <li key={r} className="flex items-center gap-2 rounded-md border px-2 py-1 text-sm">
              <span className="w-6 text-muted-foreground">{i + 1}.</span>
              <span className="flex-1 font-mono">{r}</span>
              <Button size="icon" variant="ghost" className="size-7" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${r} up`}>
                <ArrowUp />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="size-7"
                disabled={i === retrievals.length - 1}
                onClick={() => move(i, 1)}
                aria-label={`Move ${r} down`}
              >
                <ArrowDown />
              </Button>
              <Button
                size="icon"
                variant="ghost"
                className="size-7"
                onClick={() => setRetrievals(retrievals.filter((x) => x !== r))}
                aria-label={`Remove ${r}`}
              >
                <X />
              </Button>
            </li>
          ))}
        </ol>
        {unused.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {unused.map((r) => (
              <Button key={r.name} size="sm" variant="outline" onClick={() => setRetrievals([...retrievals, r.name])} aria-label={`Add ${r.name}`}>
                + {r.name}
              </Button>
            ))}
          </div>
        )}
      </fieldset>

      <SubmitBar
        label={existing ? 'Save pipeline' : 'Create pipeline'}
        pending={write.isPending}
        error={write.error}
        disabled={retrievals.length === 0 || (!existing && !name.trim())}
        onSubmit={submit}
      />
    </div>
  )
}
