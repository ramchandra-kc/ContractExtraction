import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

/** Fetches a page's data now, instead of waiting for the next poll (or when nothing polls). */
export function RefreshButton({ onRefresh, fetching }: { onRefresh: () => void; fetching: boolean }) {
  return (
    <Button variant="outline" size="icon" onClick={onRefresh} disabled={fetching} aria-label="Refresh" title="Refresh">
      <RefreshCw className={cn('size-4', fetching && 'animate-spin')} />
    </Button>
  )
}
