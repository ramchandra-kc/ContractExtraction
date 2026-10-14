import { useState } from 'react'
import { configApi, useConfigWrite, type Catalog, type CatalogModel, type CatalogProfile, type CatalogProvider } from '@/api/config'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { show, toDecimal, toInt, toText } from '@/lib/formValues'
import { DeleteButton, FormDialog, SelectInput, SubmitBar, SwitchInput, TextInput } from './form'

export function ModelsTab({ catalog }: { catalog: Catalog }) {
  return (
    <div className="space-y-6">
      {catalog.providers.map((p) => (
        <ProviderCard key={p.key} provider={p} />
      ))}
      <ProfilesCard catalog={catalog} />
    </div>
  )
}

function ProviderCard({ provider }: { provider: CatalogProvider }) {
  const update = useConfigWrite(configApi.updateProvider)
  const toggleModel = useConfigWrite(configApi.updateModel)
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          {provider.key} <Badge variant="outline">{provider.kind}</Badge>
          {!provider.is_enabled && <Badge variant="secondary">disabled</Badge>}
        </CardTitle>
        <CardDescription>
          {provider.base_url}
          {provider.api_key_env && ` · API key from $${provider.api_key_env}`}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-3">
          <SwitchInput
            label="Enabled"
            checked={provider.is_enabled}
            disabled={update.isPending}
            onChange={(on) => update.mutate({ key: provider.key, body: { is_enabled: on } })}
          />
          <FormDialog
            title={`Server for ${provider.key}`}
            description="Queued and past runs keep the URL in their snapshot."
            trigger={
              <Button size="sm" variant="outline">
                Change URL
              </Button>
            }
          >
            {(close) => <ProviderUrlForm provider={provider} onDone={close} />}
          </FormDialog>
          <FormDialog
            title={`New model on ${provider.key}`}
            trigger={
              <Button size="sm" variant="outline">
                Add model
              </Button>
            }
          >
            {(close) => <ModelForm provider={provider} onDone={close} />}
          </FormDialog>
        </div>
        <ProblemAlert error={update.error ?? toggleModel.error} />
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Model</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead className="text-right">Context</TableHead>
              <TableHead className="text-right">Dimension</TableHead>
              <TableHead className="text-right">$ / M tokens (in / out)</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {provider.models.map((m) => (
              <TableRow key={m.id}>
                <TableCell className="font-mono text-xs">{m.name}</TableCell>
                <TableCell>{m.kind}</TableCell>
                <TableCell className="text-right">{m.context_window ?? '—'}</TableCell>
                <TableCell className="text-right">{m.embedding_dimension ?? '—'}</TableCell>
                <TableCell className="text-right text-xs">
                  {m.input_cost_per_mtok ?? '—'} / {m.output_cost_per_mtok ?? '—'}
                </TableCell>
                <TableCell>
                  <Switch
                    checked={m.is_enabled}
                    disabled={toggleModel.isPending}
                    onCheckedChange={(on) => toggleModel.mutate({ id: m.id, body: { is_enabled: on } })}
                    aria-label={`${m.name} enabled`}
                  />
                </TableCell>
                <TableCell className="text-right">
                  <FormDialog
                    title={`Edit model ${m.name}`}
                    description="Name, kind and embedding dimension never change."
                    trigger={
                      <Button size="sm" variant="outline" aria-label={`Edit ${m.name}`}>
                        Edit
                      </Button>
                    }
                  >
                    {(close) => <ModelForm provider={provider} initial={m} onDone={close} />}
                  </FormDialog>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function ProviderUrlForm({ provider, onDone }: { provider: CatalogProvider; onDone: () => void }) {
  const update = useConfigWrite(configApi.updateProvider)
  const [url, setUrl] = useState(provider.base_url)
  return (
    <div className="space-y-3">
      <TextInput label="Base URL" value={url} onChange={setUrl} hint="e.g. http://localhost:11434 (native Ollama) or http://localhost:11435 (Docker)" />
      <SubmitBar
        label="Save"
        pending={update.isPending}
        error={update.error}
        onSubmit={() => update.mutate({ key: provider.key, body: { base_url: url.trim() } }, { onSuccess: onDone })}
      />
    </div>
  )
}

function ModelForm({ provider, initial, onDone }: { provider: CatalogProvider; initial?: CatalogModel; onDone: () => void }) {
  const create = useConfigWrite(configApi.createModel)
  const update = useConfigWrite(configApi.updateModel)
  const write = initial ? update : create
  const [name, setName] = useState('')
  const [kind, setKind] = useState<'chat' | 'embedding' | 'vision'>('chat')
  const [contextWindow, setContextWindow] = useState(show(initial?.context_window))
  const [dimension, setDimension] = useState('')
  const [inCost, setInCost] = useState(show(initial?.input_cost_per_mtok))
  const [outCost, setOutCost] = useState(show(initial?.output_cost_per_mtok))

  const prices = {
    context_window: toInt(contextWindow),
    input_cost_per_mtok: toDecimal(inCost),
    output_cost_per_mtok: toDecimal(outCost),
  }
  const submit = () => {
    if (initial) update.mutate({ id: initial.id, body: prices }, { onSuccess: onDone })
    else
      create.mutate(
        {
          key: provider.key,
          body: { name: name.trim(), kind, embedding_dimension: kind === 'embedding' ? toInt(dimension) : null, ...prices },
        },
        { onSuccess: onDone },
      )
  }
  return (
    <div className="space-y-3">
      {!initial && (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextInput label="Model name" value={name} onChange={setName} placeholder="llama3.2:3b" />
          <SelectInput
            label="Kind"
            value={kind}
            onChange={(v) => setKind(v as typeof kind)}
            options={['chat', 'embedding', 'vision'].map((k) => ({ value: k, label: k }))}
          />
          {kind === 'embedding' && <TextInput label="Embedding dimension" value={dimension} onChange={setDimension} hint="Cannot be changed later." />}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        <TextInput label="Context window" value={contextWindow} onChange={setContextWindow} />
        <TextInput label="Input $ / M tokens" value={inCost} onChange={setInCost} />
        <TextInput label="Output $ / M tokens" value={outCost} onChange={setOutCost} />
      </div>
      <SubmitBar label={initial ? 'Save' : 'Add model'} pending={write.isPending} error={write.error} disabled={!initial && !name.trim()} onSubmit={submit} />
    </div>
  )
}

function ProfilesCard({ catalog }: { catalog: Catalog }) {
  const remove = useConfigWrite(configApi.deleteProfile)
  return (
    <Card>
      <CardHeader>
        <CardTitle>Model profiles</CardTitle>
        <CardDescription>A model plus generation settings; pipelines use one for extraction and one for the judge.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex justify-end">
          <FormDialog title="New model profile" trigger={<Button>New profile</Button>}>
            {(close) => <ProfileForm catalog={catalog} onDone={close} />}
          </FormDialog>
        </div>
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Profile</TableHead>
              <TableHead>Model</TableHead>
              <TableHead className="text-right">Temp.</TableHead>
              <TableHead className="text-right">top_p</TableHead>
              <TableHead className="text-right">top_k</TableHead>
              <TableHead className="text-right">num_ctx</TableHead>
              <TableHead className="text-right">max tokens</TableHead>
              <TableHead>JSON</TableHead>
              <TableHead className="text-right">Timeout</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {catalog.profiles.map((p) => (
              <TableRow key={p.name} className="align-top">
                <TableCell className="whitespace-normal">
                  <span className="font-medium">{p.name}</span>
                  {p.description && <p className="text-xs text-muted-foreground">{p.description}</p>}
                </TableCell>
                <TableCell className="font-mono text-xs">
                  {p.model}@{p.provider}
                </TableCell>
                <TableCell className="text-right">{p.temperature}</TableCell>
                <TableCell className="text-right">{p.top_p ?? '—'}</TableCell>
                <TableCell className="text-right">{p.top_k ?? '—'}</TableCell>
                <TableCell className="text-right">{p.num_ctx ?? '—'}</TableCell>
                <TableCell className="text-right">{p.max_tokens ?? '—'}</TableCell>
                <TableCell>{p.json_mode ? 'on' : 'off'}</TableCell>
                <TableCell className="text-right">{p.timeout_seconds} s</TableCell>
                <TableCell className="space-x-1 text-right whitespace-nowrap">
                  <FormDialog
                    title={`Edit profile ${p.name}`}
                    trigger={
                      <Button size="sm" variant="outline" aria-label={`Edit ${p.name}`}>
                        Edit
                      </Button>
                    }
                  >
                    {(close) => <ProfileForm catalog={catalog} initial={p} onDone={close} />}
                  </FormDialog>
                  <DeleteButton
                    name={p.name}
                    pending={remove.isPending && remove.variables === p.name}
                    error={remove.variables === p.name ? remove.error : null}
                    onDelete={() => remove.mutate(p.name)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  )
}

function ProfileForm({ catalog, initial, onDone }: { catalog: Catalog; initial?: CatalogProfile; onDone: () => void }) {
  const create = useConfigWrite(configApi.createProfile)
  const update = useConfigWrite(configApi.updateProfile)
  const write = initial ? update : create
  const chatModels = catalog.providers.flatMap((p) =>
    p.models.filter((m) => m.kind !== 'embedding').map((m) => ({ value: m.id, label: `${m.name}@${p.key}${m.is_enabled ? '' : ' (disabled)'}` })),
  )
  const [name, setName] = useState('')
  const [description, setDescription] = useState(initial?.description ?? '')
  const [modelId, setModelId] = useState(initial?.model_id ?? chatModels[0]?.value ?? '')
  const [temperature, setTemperature] = useState(show(initial?.temperature ?? '0.2'))
  const [topP, setTopP] = useState(show(initial?.top_p))
  const [topK, setTopK] = useState(show(initial?.top_k))
  const [numCtx, setNumCtx] = useState(show(initial?.num_ctx ?? 8192))
  const [maxTokens, setMaxTokens] = useState(show(initial?.max_tokens))
  const [jsonMode, setJsonMode] = useState(initial?.json_mode ?? true)
  const [timeout, setTimeout_] = useState(show(initial?.timeout_seconds ?? 600))

  const body = {
    description: toText(description),
    model_id: modelId,
    temperature: temperature.trim(),
    top_p: toDecimal(topP),
    top_k: toInt(topK),
    num_ctx: toInt(numCtx),
    max_tokens: toInt(maxTokens),
    json_mode: jsonMode,
    timeout_seconds: toInt(timeout)!,
  }
  const submit = () => {
    if (initial) update.mutate({ name: initial.name, body }, { onSuccess: onDone })
    else create.mutate({ name: name.trim(), ...body }, { onSuccess: onDone })
  }
  return (
    <div className="space-y-3">
      {!initial && <TextInput label="Name" value={name} onChange={setName} placeholder="extraction-hot" hint="Cannot be changed later." />}
      <TextInput label="Description" value={description} onChange={setDescription} />
      <SelectInput label="Model" value={modelId} onChange={setModelId} options={chatModels} />
      <div className="grid gap-3 sm:grid-cols-3">
        <TextInput label="Temperature" value={temperature} onChange={setTemperature} hint="0–2" />
        <TextInput label="top_p" value={topP} onChange={setTopP} hint="0–1, blank for none" />
        <TextInput label="top_k" value={topK} onChange={setTopK} hint="blank for none" />
        <TextInput label="num_ctx" value={numCtx} onChange={setNumCtx} hint="Context window requested" />
        <TextInput label="Max tokens" value={maxTokens} onChange={setMaxTokens} hint="blank for none" />
        <TextInput label="Timeout (s)" value={timeout} onChange={setTimeout_} />
      </div>
      <SwitchInput label="JSON mode" checked={jsonMode} onChange={setJsonMode} />
      <SubmitBar label={initial ? 'Save' : 'Create'} pending={write.isPending} error={write.error} disabled={!initial && !name.trim()} onSubmit={submit} />
    </div>
  )
}
