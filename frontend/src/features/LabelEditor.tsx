import { useId, useState } from 'react'
import { JsonValue } from '@/components/JsonValue'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { fromDraft, hintFor, isAbsent, type LabelDraft } from '@/lib/groundTruth'

/** A ground-truth label: "Not in this contract" for "", otherwise the value; a dash when unlabelled. */
export function LabelValue({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="text-muted-foreground">—</span>
  if (isAbsent(value)) return <span className="text-muted-foreground italic">Not in this contract</span>
  return <JsonValue value={value} />
}

interface Props {
  valueType: string
  initial: LabelDraft
  initialNotes?: string | null
  pending?: boolean
  error?: unknown
  onSave: (value: unknown, notes: string) => void
  onCancel: () => void
}

/** Form for one label: the value (shaped by value type) or "not in this contract", plus notes. */
export function LabelEditor({ valueType, initial, initialNotes, pending, error, onSave, onCancel }: Props) {
  const id = useId()
  const [draft, setDraft] = useState(initial)
  const [notes, setNotes] = useState(initialNotes ?? '')
  const [invalid, setInvalid] = useState<string | null>(null)

  const save = () => {
    const parsed = fromDraft(draft, valueType)
    if (!parsed.ok) return setInvalid(parsed.error)
    setInvalid(null)
    onSave(parsed.value, notes.trim())
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-3">
        <Switch
          id={`${id}-absent`}
          checked={draft.absent}
          onCheckedChange={(absent) => setDraft({ ...draft, absent })}
        />
        <Label htmlFor={`${id}-absent`} className="font-normal">
          Not in this contract
        </Label>
      </div>
      {!draft.absent && (
        <div className="space-y-1">
          <Label htmlFor={`${id}-value`}>Expected value</Label>
          <Textarea
            id={`${id}-value`}
            value={draft.text}
            rows={valueType === 'list' || valueType === 'json' ? 4 : 2}
            className={valueType === 'json' ? 'font-mono text-xs' : undefined}
            onChange={(e) => setDraft({ ...draft, text: e.target.value })}
          />
          <p className="text-xs text-muted-foreground">{hintFor(valueType)}</p>
        </div>
      )}
      <div className="space-y-1">
        <Label htmlFor={`${id}-notes`}>Notes</Label>
        <Input id={`${id}-notes`} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional" />
      </div>
      {invalid && (
        <p role="alert" className="text-sm text-red-700">
          {invalid}
        </p>
      )}
      <ProblemAlert error={error} />
      <div className="flex gap-2">
        <Button size="sm" onClick={save} disabled={pending}>
          {pending ? 'Saving…' : 'Save'}
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={pending}>
          Cancel
        </Button>
      </div>
    </div>
  )
}
