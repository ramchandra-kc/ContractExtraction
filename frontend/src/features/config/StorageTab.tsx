import { useState } from 'react'
import { configApi, useConfigWrite, type Catalog } from '@/api/config'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { toInt, toText } from '@/lib/formValues'
import { DeleteButton, FormDialog, SelectInput, SubmitBar, SwitchInput, TextInput } from './form'

const CREATE_ONLY =
  'Create-only: decompositions and vector indexes are reused by config id, so a config never changes after it is made. Create a new one instead.'

/** Decomposition and index configs: listed, created and deleted (when unused), never edited. */
export function StorageTab({ catalog }: { catalog: Catalog }) {
  const removeDecomposition = useConfigWrite(configApi.deleteDecomposition)
  const removeIndex = useConfigWrite(configApi.deleteIndex)
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Decomposition configs</CardTitle>
          <CardDescription>{CREATE_ONLY}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-end">
            <FormDialog title="New decomposition config" description={CREATE_ONLY} trigger={<Button>New decomposition config</Button>}>
              {(close) => <DecompositionForm onDone={close} />}
            </FormDialog>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Method</TableHead>
                <TableHead>Format</TableHead>
                <TableHead>Invisible text</TableHead>
                <TableHead>Headers/footers removed</TableHead>
                <TableHead>OCR language</TableHead>
                <TableHead className="text-right">DPI</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {catalog.decompositions.map((d) => (
                <TableRow key={d.name}>
                  <TableCell className="font-medium">{d.name}</TableCell>
                  <TableCell>{d.method}</TableCell>
                  <TableCell>{d.text_format}</TableCell>
                  <TableCell>{d.keep_invisible_text ? 'kept' : 'dropped'}</TableCell>
                  <TableCell>{d.remove_headers_footers ? 'yes' : 'no'}</TableCell>
                  <TableCell>{d.ocr_language}</TableCell>
                  <TableCell className="text-right">{d.dpi}</TableCell>
                  <TableCell className="text-right">
                    <DeleteButton
                      name={d.name}
                      pending={removeDecomposition.isPending && removeDecomposition.variables === d.name}
                      error={removeDecomposition.variables === d.name ? removeDecomposition.error : null}
                      onDelete={() => removeDecomposition.mutate(d.name)}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Index configs</CardTitle>
          <CardDescription>{CREATE_ONLY}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex justify-end">
            <FormDialog title="New index config" description={CREATE_ONLY} trigger={<Button>New index config</Button>}>
              {(close) => <IndexForm catalog={catalog} onDone={close} />}
            </FormDialog>
          </div>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Embedding model</TableHead>
                <TableHead className="text-right">Chunk size / overlap</TableHead>
                <TableHead>Store</TableHead>
                <TableHead>Distance</TableHead>
                <TableHead className="text-right">Batch</TableHead>
                <TableHead className="text-right">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {catalog.indexes.map((x) => (
                <TableRow key={x.name}>
                  <TableCell className="font-medium">{x.name}</TableCell>
                  <TableCell className="font-mono text-xs">{x.embedding_model}</TableCell>
                  <TableCell className="text-right">
                    {x.chunk_size} / {x.chunk_overlap}
                  </TableCell>
                  <TableCell>{x.vector_store}</TableCell>
                  <TableCell>{x.distance}</TableCell>
                  <TableCell className="text-right">{x.batch_size}</TableCell>
                  <TableCell className="text-right">
                    <DeleteButton
                      name={x.name}
                      pending={removeIndex.isPending && removeIndex.variables === x.name}
                      error={removeIndex.variables === x.name ? removeIndex.error : null}
                      onDelete={() => removeIndex.mutate(x.name)}
                    />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  )
}

function DecompositionForm({ onDone }: { onDone: () => void }) {
  const write = useConfigWrite(configApi.createDecomposition)
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [method, setMethod] = useState<'pymupdf' | 'ocr' | 'hybrid'>('pymupdf')
  const [textFormat, setTextFormat] = useState<'md' | 'html'>('md')
  const [invisible, setInvisible] = useState(true)
  const [headers, setHeaders] = useState(true)
  const [language, setLanguage] = useState('eng')
  const [dpi, setDpi] = useState('200')
  const submit = () =>
    write.mutate(
      {
        name: name.trim(),
        description: toText(description),
        method,
        text_format: textFormat,
        keep_invisible_text: invisible,
        remove_headers_footers: headers,
        ocr_language: language.trim(),
        dpi: toInt(dpi)!,
      },
      { onSuccess: onDone },
    )
  return (
    <div className="space-y-3">
      <TextInput label="Name" value={name} onChange={setName} placeholder="ocr-300dpi" />
      <TextInput label="Description" value={description} onChange={setDescription} />
      <div className="grid gap-3 sm:grid-cols-2">
        <SelectInput
          label="Method"
          value={method}
          onChange={(v) => setMethod(v as typeof method)}
          options={['pymupdf', 'ocr', 'hybrid'].map((m) => ({ value: m, label: m }))}
        />
        <SelectInput
          label="Text format"
          value={textFormat}
          onChange={(v) => setTextFormat(v as typeof textFormat)}
          options={['md', 'html'].map((f) => ({ value: f, label: f }))}
        />
        <TextInput label="OCR language" value={language} onChange={setLanguage} hint="Tesseract code, e.g. eng" />
        <TextInput label="DPI" value={dpi} onChange={setDpi} hint="72–1200" />
      </div>
      <SwitchInput label="Keep invisible (OCR) text" checked={invisible} onChange={setInvisible} />
      <SwitchInput label="Remove repeated headers and footers" checked={headers} onChange={setHeaders} />
      <SubmitBar label="Create" pending={write.isPending} error={write.error} disabled={!name.trim()} onSubmit={submit} />
    </div>
  )
}

function IndexForm({ catalog, onDone }: { catalog: Catalog; onDone: () => void }) {
  const write = useConfigWrite(configApi.createIndex)
  const embeddingModels = catalog.providers.flatMap((p) =>
    p.models.filter((m) => m.kind === 'embedding').map((m) => ({ value: m.id, label: `${m.name}@${p.key} (${m.embedding_dimension} dims)` })),
  )
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [modelId, setModelId] = useState(embeddingModels[0]?.value ?? '')
  const [chunkSize, setChunkSize] = useState('2000')
  const [overlap, setOverlap] = useState('300')
  const [distance, setDistance] = useState<'cosine' | 'dot' | 'euclid'>('cosine')
  const [batch, setBatch] = useState('32')
  const submit = () =>
    write.mutate(
      {
        name: name.trim(),
        description: toText(description),
        embedding_model_id: modelId,
        chunk_size: toInt(chunkSize)!,
        chunk_overlap: toInt(overlap)!,
        vector_store: 'qdrant',
        distance,
        batch_size: toInt(batch)!,
      },
      { onSuccess: onDone },
    )
  return (
    <div className="space-y-3">
      <TextInput label="Name" value={name} onChange={setName} placeholder="chunks-1000" />
      <TextInput label="Description" value={description} onChange={setDescription} />
      <SelectInput label="Embedding model" value={modelId} onChange={setModelId} options={embeddingModels} />
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput label="Chunk size" value={chunkSize} onChange={setChunkSize} hint="Characters" />
        <TextInput label="Chunk overlap" value={overlap} onChange={setOverlap} hint="Smaller than the chunk size" />
        <SelectInput
          label="Distance"
          value={distance}
          onChange={(v) => setDistance(v as typeof distance)}
          options={['cosine', 'dot', 'euclid'].map((d) => ({ value: d, label: d }))}
        />
        <TextInput label="Embedding batch size" value={batch} onChange={setBatch} />
      </div>
      <SubmitBar label="Create" pending={write.isPending} error={write.error} disabled={!name.trim() || !modelId} onSubmit={submit} />
    </div>
  )
}
