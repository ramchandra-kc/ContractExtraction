import { Link, useSearchParams } from 'react-router'
import { useDocuments } from '@/api/hooks'
import { Pager } from '@/components/Pager'
import { ProblemAlert } from '@/components/ProblemAlert'
import { RefreshButton } from '@/components/RefreshButton'
import { StateBadge } from '@/components/StateBadge'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { UploadDropzone } from '@/features/UploadDropzone'
import { formatBytes, formatDateTime } from '@/lib/format'

const LIMIT = 25

export function DocumentsPage() {
  const [params, setParams] = useSearchParams()
  const offset = Math.max(0, Number(params.get('offset')) || 0)
  const documents = useDocuments(LIMIT, offset)

  return (
    <div className="space-y-6">
      <UploadDropzone />
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle>Documents</CardTitle>
          <RefreshButton fetching={documents.isFetching} onRefresh={() => documents.refetch()} />
        </CardHeader>
        <CardContent className="space-y-3">
          <ProblemAlert error={documents.error} />
          {documents.isPending ? (
            <Skeleton className="h-24" />
          ) : documents.data?.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">No documents yet. Upload a contract file to start.</p>
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
                  onChange={(o) => setParams(o ? { offset: String(o) } : {})}
                />
              </>
            )
          )}
        </CardContent>
      </Card>
    </div>
  )
}
