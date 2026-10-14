import { useRef, useState, type DragEvent } from 'react'
import { useNavigate } from 'react-router'
import { toast } from 'sonner'
import { Upload } from 'lucide-react'
import { useUploadDocument } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { cn } from '@/lib/utils'

/** Drop or pick a PDF. A file stored before (200) opens the existing document. */
export function UploadDropzone() {
  const upload = useUploadDocument()
  const navigate = useNavigate()
  const input = useRef<HTMLInputElement>(null)
  const [dragging, setDragging] = useState(false)

  const send = (file: File | undefined) => {
    if (!file) return
    upload.mutate(file, {
      onSuccess: ({ document, created }) => {
        if (created) toast.success(`Uploaded ${document.code}`)
        else toast.info(`Already uploaded as ${document.code}`)
        navigate(`/documents/${document.id}`)
      },
    })
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setDragging(false)
    send(e.dataTransfer.files[0])
  }

  return (
    <div className="space-y-3">
      <button
        type="button"
        onClick={() => input.current?.click()}
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={onDrop}
        disabled={upload.isPending}
        className={cn(
          'flex w-full flex-col items-center gap-2 rounded-lg border-2 border-dashed p-8 text-sm text-muted-foreground transition-colors',
          dragging ? 'border-primary bg-accent' : 'hover:bg-accent/50',
        )}
      >
        <Upload className="size-6" />
        {upload.isPending ? 'Uploading…' : 'Drop a contract PDF here, or click to choose one'}
      </button>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="hidden"
        aria-label="PDF file"
        onChange={(e) => {
          send(e.target.files?.[0])
          e.target.value = ''
        }}
      />
      <ProblemAlert error={upload.error} />
    </div>
  )
}
