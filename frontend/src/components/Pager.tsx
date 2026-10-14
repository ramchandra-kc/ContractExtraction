import { Button } from '@/components/ui/button'

export function Pager({ total, limit, offset, onChange }: { total: number; limit: number; offset: number; onChange: (offset: number) => void }) {
  if (total <= limit) return null
  return (
    <div className="flex items-center justify-end gap-2 text-sm text-muted-foreground">
      {offset + 1}–{Math.min(offset + limit, total)} of {total}
      <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
        Previous
      </Button>
      <Button variant="outline" size="sm" disabled={offset + limit >= total} onClick={() => onChange(offset + limit)}>
        Next
      </Button>
    </div>
  )
}
