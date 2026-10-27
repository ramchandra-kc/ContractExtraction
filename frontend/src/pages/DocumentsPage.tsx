import { Search } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router'
import { useDocuments } from '@/api/hooks'
import { Pager } from '@/components/Pager'
import { ProblemAlert } from '@/components/ProblemAlert'
import { RefreshButton } from '@/components/RefreshButton'
import { StateBadge } from '@/components/StateBadge'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { UploadDropzone } from '@/features/UploadDropzone'
import { formatBytes, formatDateTime } from '@/lib/format'

const LIMIT = 25
const SEARCH_DELAY_MS = 300

export function DocumentsPage() {
  const [params, setParams] = useSearchParams()
  const offset = Math.max(0, Number(params.get('offset')) || 0)
  const q = params.get('q')?.trim() ?? ''
  const [search, setSearch] = useState(q)
  const [urlQ, setUrlQ] = useState(q)
  if (q !== urlQ) {
    // The URL changed under the box (back/forward): show what it searches for.
    setUrlQ(q)
    if (search.trim() !== q) setSearch(q)
  }
  const documents = useDocuments(LIMIT, offset, q)

  // The URL follows the box after a pause in typing; a new search starts at the first page.
  useEffect(() => {
    if (search.trim() === q) return
    const timer = setTimeout(() => setParams(search.trim() ? { q: search.trim() } : {}), SEARCH_DELAY_MS)
    return () => clearTimeout(timer)
  }, [search, q, setParams])

  const page = (o: number) => setParams({ ...(q && { q }), ...(o && { offset: String(o) }) })

  return (
    <div className="space-y-6">
      <UploadDropzone />
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle>Documents</CardTitle>
          <div className="flex items-center gap-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
              <Input
                type="search"
                aria-label="Search documents"
                placeholder="Search code, title or filename"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="w-64 pl-8"
              />
            </div>
            <RefreshButton fetching={documents.isFetching} onRefresh={() => documents.refetch()} />
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <ProblemAlert error={documents.error} />
          {documents.isPending ? (
            <Skeleton className="h-24" />
          ) : documents.data?.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              {q ? `No documents match “${q}”.` : 'No documents yet. Upload a contract file to start.'}
            </p>
          ) : (
            documents.data && (
              <>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Code</TableHead>
                      <TableHead>Document</TableHead>
                      <TableHead className="text-right">Pages</TableHead>
                      <TableHead className="text-right">Size</TableHead>
                      <TableHead>Latest run</TableHead>
                      <TableHead>Uploaded</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {documents.data.items.map((d) => (
                      <TableRow key={d.id}>
                        <TableCell className="font-mono">
                          <Link to={`/documents/${d.id}`} className="underline-offset-4 hover:underline">
                            {d.code}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Link to={`/documents/${d.id}`} className="underline-offset-4 hover:underline">
                            {d.title || d.original_filename}
                          </Link>
                          <Badge variant="outline" className="ml-2 uppercase">
                            {d.format}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right">{d.page_count ?? '—'}</TableCell>
                        <TableCell className="text-right">{formatBytes(d.size_bytes)}</TableCell>
                        <TableCell>
                          {d.latest_run ? (
                            <Link to={`/runs/${d.latest_run.id}`} className="flex items-center gap-2">
                              <StateBadge state={d.latest_run.state} stage={d.latest_run.stage} />
                              {d.latest_run.state === 'running' && d.latest_run.progress_total > 0 && (
                                <span className="text-xs text-muted-foreground">
                                  {d.latest_run.progress_done}/{d.latest_run.progress_total}
                                </span>
                              )}
                            </Link>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </TableCell>
                        <TableCell>{formatDateTime(d.created_at)}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
                <Pager
                  total={documents.data.total}
                  limit={LIMIT}
                  offset={offset}
                  onChange={page}
                />
              </>
            )
          )}
        </CardContent>
      </Card>
    </div>
  )
}
