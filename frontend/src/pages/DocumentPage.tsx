import { Link, useParams } from 'react-router'
import { documentFileUrl } from '@/api/client'
import { useDocument } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { StateBadge } from '@/components/StateBadge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { GroundTruthCard } from '@/features/GroundTruthCard'
import { NewRunDialog } from '@/features/NewRunDialog'
import { formatBytes, formatDateTime, formatMs, formatSpan } from '@/lib/format'

export function DocumentPage() {
  const { id } = useParams()
  const { data: doc, error, isPending } = useDocument(id)

  if (error) return <ProblemAlert error={error} />
  if (isPending || !doc) return <Skeleton className="h-64" />
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="font-mono text-sm text-muted-foreground">{doc.code}</p>
          <h1 className="text-2xl font-semibold">{doc.title || doc.original_filename}</h1>
          <p className="text-sm text-muted-foreground">
            {doc.original_filename} · {formatBytes(doc.size_bytes)} · {doc.page_count ?? '?'} pages · uploaded{' '}
            {formatDateTime(doc.created_at)}
          </p>
          {doc.tags.length > 0 && <p className="text-sm text-muted-foreground">Tags: {doc.tags.join(', ')}</p>}
        </div>
        <div className="flex gap-2">
          <Button variant="outline" asChild>
            <a href={documentFileUrl(doc.id)} target="_blank" rel="noreferrer">
              Open PDF
            </a>
          </Button>
          {doc.decompositions.length > 0 && (
            <Button variant="outline" asChild>
              <Link to={`/documents/${doc.id}/pages`}>View pages</Link>
            </Button>
          )}
          <NewRunDialog document={doc} />
        </div>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Runs</CardTitle>
        </CardHeader>
        <CardContent>
          {doc.runs.length === 0 ? (
            <p className="text-sm text-muted-foreground">No runs yet. Start one with “New run”.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Queued</TableHead>
                  <TableHead>Kind</TableHead>
                  <TableHead>State</TableHead>
                  <TableHead className="text-right">Progress</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                  <TableHead>Error</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {doc.runs.map((r) => (
                  <TableRow key={r.id}>
                    <TableCell>
                      <Link to={`/runs/${r.id}`} className="underline-offset-4 hover:underline">
                        {formatDateTime(r.queued_at)}
                      </Link>
                    </TableCell>
                    <TableCell>{r.kind}</TableCell>
                    <TableCell>
                      <StateBadge state={r.state} stage={r.stage} />
                    </TableCell>
                    <TableCell className="text-right">
                      {r.progress_total ? `${r.progress_done}/${r.progress_total}` : '—'}
                    </TableCell>
                    <TableCell className="text-right">{formatSpan(r.started_at, r.finished_at)}</TableCell>
                    <TableCell className="max-w-xs truncate text-red-700" title={r.error ?? undefined}>
                      {r.error}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      <GroundTruthCard documentId={doc.id} />

      {doc.decompositions.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Decompositions</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Created</TableHead>
                  <TableHead>Config</TableHead>
                  <TableHead>Method</TableHead>
                  <TableHead>Format</TableHead>
                  <TableHead className="text-right">Pages</TableHead>
                  <TableHead className="text-right">Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {doc.decompositions.map((d) => (
                  <TableRow key={d.id}>
                    <TableCell>
                      <Link
                        to={`/documents/${doc.id}/pages?decomposition=${d.id}`}
                        className="underline-offset-4 hover:underline"
                      >
                        {formatDateTime(d.created_at)}
                      </Link>
                    </TableCell>
                    <TableCell>{d.config ?? '—'}</TableCell>
                    <TableCell>{d.method ?? '—'}</TableCell>
                    <TableCell>{d.text_format ?? '—'}</TableCell>
                    <TableCell className="text-right">{d.page_count}</TableCell>
                    <TableCell className="text-right">{formatMs(d.duration_ms)}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  )
}
