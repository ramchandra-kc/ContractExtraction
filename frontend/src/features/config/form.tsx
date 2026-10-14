import { useId, useState, type ReactElement, type ReactNode } from 'react'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'

/** A dialog whose form is mounted only while open, so it starts from fresh values each time. */
export function FormDialog({
  title,
  description,
  trigger,
  wide,
  children,
}: {
  title: string
  description?: string
  trigger: ReactElement
  wide?: boolean
  children: (close: () => void) => ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>{trigger}</DialogTrigger>
      <DialogContent className={wide ? 'max-h-[90vh] overflow-y-auto sm:max-w-3xl' : 'max-h-[90vh] overflow-y-auto sm:max-w-xl'}>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description ?? 'Runs already queued or finished keep the configuration they started with.'}</DialogDescription>
        </DialogHeader>
        {open && children(() => setOpen(false))}
      </DialogContent>
    </Dialog>
  )
}

export function TextInput({
  label,
  value,
  onChange,
  hint,
  rows,
  mono,
  placeholder,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  hint?: string
  rows?: number
  mono?: boolean
  placeholder?: string
}) {
  const id = useId()
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      {rows ? (
        <Textarea
          id={id}
          rows={rows}
          value={value}
          placeholder={placeholder}
          className={mono ? 'font-mono text-xs' : undefined}
          onChange={(e) => onChange(e.target.value)}
        />
      ) : (
        <Input id={id} value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
      )}
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

export function SelectInput({
  label,
  value,
  onChange,
  options,
}: {
  label: string
  value: string
  onChange: (v: string) => void
  options: { value: string; label: string; disabled?: boolean }[]
}) {
  const id = useId()
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Select value={value} onValueChange={onChange}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue placeholder="Choose…" />
        </SelectTrigger>
        <SelectContent>
          {options.map((o) => (
            <SelectItem key={o.value} value={o.value} disabled={o.disabled}>
              {o.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  )
}

export function SwitchInput({
  label,
  checked,
  onChange,
  disabled,
}: {
  label: string
  checked: boolean
  onChange: (v: boolean) => void
  disabled?: boolean
}) {
  const id = useId()
  return (
    <div className="flex items-center gap-3">
      <Switch id={id} checked={checked} onCheckedChange={onChange} disabled={disabled} />
      <Label htmlFor={id} className="font-normal">
        {label}
      </Label>
    </div>
  )
}

export function SubmitBar({
  label,
  pending,
  error,
  disabled,
  onSubmit,
}: {
  label: string
  pending: boolean
  error: unknown
  disabled?: boolean
  onSubmit: () => void
}) {
  return (
    <div className="space-y-3 pt-2">
      <ProblemAlert error={error} />
      <div className="flex justify-end">
        <Button onClick={onSubmit} disabled={pending || disabled}>
          {pending ? 'Saving…' : label}
        </Button>
      </div>
    </div>
  )
}

/** Delete in two clicks (no browser dialog); the API's 409 "in use" problem is shown in place. */
export function DeleteButton({
  name,
  pending,
  error,
  onDelete,
}: {
  name: string
  pending: boolean
  error: unknown
  onDelete: () => void
}) {
  const [armed, setArmed] = useState(false)
  return (
    <span className="inline-flex flex-col items-end gap-2">
      {armed ? (
        <span className="inline-flex gap-1">
          <Button size="sm" variant="destructive" disabled={pending} onClick={onDelete} aria-label={`Confirm delete ${name}`}>
            {pending ? 'Deleting…' : 'Confirm delete'}
          </Button>
          <Button size="sm" variant="ghost" onClick={() => setArmed(false)}>
            Keep
          </Button>
        </span>
      ) : (
        <Button size="sm" variant="ghost" onClick={() => setArmed(true)} aria-label={`Delete ${name}`}>
          Delete
        </Button>
      )}
      {error ? (
        <span className="max-w-sm text-left">
          <ProblemAlert error={error} />
        </span>
      ) : null}
    </span>
  )
}
