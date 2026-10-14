import type { ReactNode } from 'react'
import { CircleAlert } from 'lucide-react'
import { ProblemError } from '@/api/client'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'

/** Shows an API/gateway problem (or any error) with its validation errors and request id. */
export function ProblemAlert({ error, children }: { error: unknown; children?: ReactNode }) {
  if (!error) return null
  const p = error instanceof ProblemError ? error : null
  const title = p ? (p.status ? `${p.status} ${p.title}` : p.title) : 'Something went wrong'
  const detail = p ? p.detail : error instanceof Error ? error.message : String(error)
  return (
    <Alert variant="destructive" role="alert">
      <CircleAlert />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        {detail && <p>{detail}</p>}
        {p && p.errors.length > 0 && (
          <ul className="list-disc pl-4">
            {p.errors.map((e, i) => (
              <li key={i}>
                <code>{e.loc.join('.')}</code>: {e.msg}
              </li>
            ))}
          </ul>
        )}
        {children}
        {p?.requestId && <p className="text-xs opacity-70">Request id: {p.requestId}</p>}
      </AlertDescription>
    </Alert>
  )
}
