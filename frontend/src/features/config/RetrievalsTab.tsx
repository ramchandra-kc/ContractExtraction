import { useState } from 'react'
import { configApi, useConfigWrite, type Catalog, type CatalogRetrieval } from '@/api/config'
import { Button } from '@/components/ui/button'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { show, toInt, toText } from '@/lib/formValues'
import { DeleteButton, FormDialog, SubmitBar, SwitchInput, TextInput } from './form'

export function RetrievalsTab({ catalog }: { catalog: Catalog }) {
  const remove = useConfigWrite(configApi.deleteRetrieval)
  const used = new Set(catalog.pipelines.flatMap((p) => p.retrievals))
  return (
    <div className="space-y-3">
      <div className="flex justify-end">
        <FormDialog title="New RAG config" trigger={<Button>New RAG config</Button>}>
          {(close) => <RetrievalForm onDone={close} />}
        </FormDialog>
      </div>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead className="text-right">Top k</TableHead>
            <TableHead className="text-right">Threshold</TableHead>
            <TableHead>Query expansion</TableHead>
            <TableHead className="text-right">Per query</TableHead>
            <TableHead className="text-right">Min score</TableHead>
            <TableHead>Description</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {catalog.retrievals.map((r) => (
            <TableRow key={r.name} className="align-top">
              <TableCell className="font-mono">{r.name}</TableCell>
              <TableCell className="text-right">{r.top_k}</TableCell>
              <TableCell className="text-right">{r.score_threshold}</TableCell>
              <TableCell>{r.query_expansion ? 'on' : 'off'}</TableCell>
              <TableCell className="text-right">{r.per_query_top}</TableCell>
              <TableCell className="text-right">{r.min_score}</TableCell>
              <TableCell className="text-xs whitespace-normal text-muted-foreground">
                {r.description}
                {!used.has(r.name) && <span className="block">Not used by any pipeline</span>}
              </TableCell>
              <TableCell className="space-x-1 text-right whitespace-nowrap">
                <FormDialog
                  title={`Edit RAG config ${r.name}`}
                  trigger={
                    <Button size="sm" variant="outline" aria-label={`Edit ${r.name}`}>
                      Edit
                    </Button>
                  }
                >
                  {(close) => <RetrievalForm initial={r} onDone={close} />}
                </FormDialog>
                <DeleteButton
                  name={r.name}
                  pending={remove.isPending && remove.variables === r.name}
                  error={remove.variables === r.name ? remove.error : null}
                  onDelete={() => remove.mutate(r.name)}
                />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  )
}

function RetrievalForm({ initial, onDone }: { initial?: CatalogRetrieval; onDone: () => void }) {
  const create = useConfigWrite(configApi.createRetrieval)
  const update = useConfigWrite(configApi.updateRetrieval)
  const write = initial ? update : create
  const [name, setName] = useState('')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [topK, setTopK] = useState(show(initial?.top_k ?? 5))
  const [threshold, setThreshold] = useState(show(initial?.score_threshold ?? '0.5'))
  const [expansion, setExpansion] = useState(initial?.query_expansion ?? true)
  const [perQuery, setPerQuery] = useState(show(initial?.per_query_top ?? 3))
  const [minScore, setMinScore] = useState(show(initial?.min_score ?? '0.3'))

  const body = {
    description: toText(description),
    top_k: toInt(topK)!,
    score_threshold: threshold.trim(),
    query_expansion: expansion,
    per_query_top: toInt(perQuery)!,
    min_score: minScore.trim(),
  }
  const submit = () => {
    if (initial) update.mutate({ name: initial.name, body }, { onSuccess: onDone })
    else create.mutate({ name: name.trim(), ...body }, { onSuccess: onDone })
  }
  return (
    <div className="space-y-3">
      {!initial && <TextInput label="Name" value={name} onChange={setName} placeholder="RAG08" hint="Cannot be changed later." />}
      <TextInput label="Description" value={description} onChange={setDescription} />
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput label="Top k" value={topK} onChange={setTopK} hint="Chunks passed to the extraction model." />
        <TextInput label="Score threshold" value={threshold} onChange={setThreshold} hint="0–1; a hit must score at least this." />
        <TextInput label="Hits per query" value={perQuery} onChange={setPerQuery} hint="Fetched per expanded query before merging." />
        <TextInput label="Minimum score" value={minScore} onChange={setMinScore} hint="0–1; floor applied after merging." />
      </div>
      <SwitchInput label="Query expansion (search with the field's queries, not only its label)" checked={expansion} onChange={setExpansion} />
      <SubmitBar
        label={initial ? 'Save' : 'Create'}
        pending={write.isPending}
        error={write.error}
        disabled={!initial && !name.trim()}
        onSubmit={submit}
      />
    </div>
  )
}
