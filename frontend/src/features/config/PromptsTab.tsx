import { useState } from 'react'
import { configApi, useConfigWrite, type Catalog, type CatalogPrompt } from '@/api/config'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { formatDateTime } from '@/lib/format'
import { toText } from '@/lib/formValues'
import { FormDialog, SelectInput, SubmitBar, TextInput } from './form'

const ROLES = ['extraction_system', 'judge_system', 'caption'] as const

/** Prompts are versioned: saving creates the next version; pipelines keep the version they are set to. */
export function PromptsTab({ catalog }: { catalog: Catalog }) {
  const byName = new Map<string, CatalogPrompt[]>()
  for (const p of catalog.prompts) byName.set(p.name, [...(byName.get(p.name) ?? []), p])
  const pinned = (p: CatalogPrompt) =>
    catalog.pipelines
      .filter(
        (x) =>
          (x.extraction_prompt.name === p.name && x.extraction_prompt.version === p.version) ||
          (x.judge_prompt?.name === p.name && x.judge_prompt?.version === p.version),
      )
      .map((x) => x.name)

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <FormDialog title="New prompt" description="Starts at version 1." wide trigger={<Button>New prompt</Button>}>
          {(close) => <NewPromptForm onDone={close} />}
        </FormDialog>
      </div>
      {[...byName].map(([name, versions]) => {
        const active = versions.find((v) => v.is_active) ?? versions[0]
        return (
          <Card key={name}>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                {name} <Badge variant="outline">{active.role}</Badge>
              </CardTitle>
              <CardDescription>
                Versions:{' '}
                {versions.map((v) => {
                  const users = pinned(v)
                  return (
                    <span key={v.version} className="mr-3">
                      v{v.version}
                      {v.is_active && ' (active)'}
                      {users.length > 0 && ` — used by ${users.join(', ')}`}
                    </span>
                  )
                })}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-muted-foreground">
                Active version v{active.version}, {formatDateTime(active.created_at)}
                {active.notes && ` · ${active.notes}`}
              </p>
              <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">{active.body}</pre>
              <FormDialog
                title={`New version of ${name}`}
                description={`Saves v${Math.max(...versions.map((v) => v.version)) + 1} and makes it active. Pipelines keep their version until you change them.`}
                wide
                trigger={
                  <Button size="sm" variant="outline" aria-label={`New version of ${name}`}>
                    New version
                  </Button>
                }
              >
                {(close) => <VersionForm name={name} body={active.body} onDone={close} />}
              </FormDialog>
            </CardContent>
          </Card>
        )
      })}
    </div>
  )
}

function VersionForm({ name, body: initialBody, onDone }: { name: string; body: string; onDone: () => void }) {
  const write = useConfigWrite(configApi.createPromptVersion)
  const [body, setBody] = useState(initialBody)
  const [notes, setNotes] = useState('')
  return (
    <div className="space-y-3">
      <TextInput label="Prompt" value={body} onChange={setBody} rows={16} mono />
      <TextInput label="Notes" value={notes} onChange={setNotes} placeholder="What changed and why" />
      <SubmitBar
        label="Save new version"
        pending={write.isPending}
        error={write.error}
        disabled={!body.trim() || body === initialBody}
        onSubmit={() => write.mutate({ name, body: { body, notes: toText(notes) } }, { onSuccess: onDone })}
      />
    </div>
  )
}

function NewPromptForm({ onDone }: { onDone: () => void }) {
  const write = useConfigWrite(configApi.createPrompt)
  const [name, setName] = useState('')
  const [role, setRole] = useState<(typeof ROLES)[number]>('extraction_system')
  const [body, setBody] = useState('')
  return (
    <div className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <TextInput label="Name" value={name} onChange={setName} hint="Cannot be changed later." />
        <SelectInput label="Role" value={role} onChange={(v) => setRole(v as typeof role)} options={ROLES.map((r) => ({ value: r, label: r }))} />
      </div>
      <TextInput label="Prompt" value={body} onChange={setBody} rows={12} mono />
      <SubmitBar
        label="Create prompt"
        pending={write.isPending}
        error={write.error}
        disabled={!name.trim() || !body.trim()}
        onSubmit={() => write.mutate({ name: name.trim(), role, body }, { onSuccess: onDone })}
      />
    </div>
  )
}
