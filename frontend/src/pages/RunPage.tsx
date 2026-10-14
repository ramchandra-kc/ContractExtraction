import { Link, useParams, useSearchParams } from 'react-router'
import { isActive, useCancelRun, useDocument, useRun, useRunEvents, useRunResults } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { StateBadge } from '@/components/StateBadge'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Progress } from '@/components/ui/progress'
import { Skeleton } from '@/components/ui/skeleton'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { EventsTimeline } from '@/features/EventsTimeline'
import { FieldResultSheet } from '@/features/FieldResultSheet'
import { OutcomesMatrix } from '@/features/OutcomesMatrix'
import { ResultsTable } from '@/features/ResultsTable'
import { formatDateTime, formatSpan } from '@/lib/format'

export function RunPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const run = useRun(id)
  const active = isActive(run.data?.state)
  const events = useRunEvents(id, active)
  const results = useRunResults(id, active)
  const document = useDocument(run.data?.document_id)
  const cancel = useCancelRun()

  const resultId = params.get('result')
  const openResult = (rid: string) => setParams({ result: rid })
  const closeResult = () => setParams({})

  if (run.error) return <ProblemAlert error={run.error} />
  if (run.isPending) return <Skeleton className="h-64" />
  const r = run.data
  const percent = r.progress_total ? Math.round((100 * r.progress_done) / r.progress_total) : 0

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-1">
          <p className="text-sm text-muted-foreground">
            <Link to={`/documents/${r.document_id}`} className="underline-offset-4 hover:underline">
              {document.data ? `${document.data.code} · ${document.data.title || document.data.original_filename}` : 'Document'}
            </Link>
          </p>
          <h1 className="flex items-center gap-3 text-2xl font-semibold">
            Run <StateBadge state={r.state} stage={r.stage} />
          </h1>
          <p className="text-sm text-muted-foreground">
            {r.kind} · pipeline {r.pipeline ?? '—'} · queued {formatDateTime(r.queued_at)} · duration{' '}
            {formatSpan(r.started_at, r.finished_at)}
            {r.worker_id && ` · worker ${r.worker_id}`}
          </p>
        </div>
        <div className="flex gap-2">
          {r.decomposition_id && (
            <Button variant="outline" asChild>
              <Link to={`/documents/${r.document_id}/pages?decomposition=${r.decomposition_id}`}>View pages</Link>
            </Button>
          )}
          {active && (
            <Button
              variant="destructive"
              disabled={r.cancel_requested || cancel.isPending}
              onClick={() => cancel.mutate(r.id)}
            >
              {r.cancel_requested ? 'Cancelling…' : 'Cancel run'}
            </Button>
          )}
        </div>
      </div>

      <ProblemAlert error={cancel.error} />

      {active && (
        <Card>
          <CardContent className="space-y-2 pt-6">
            <div className="flex justify-between text-sm">
              <span>{r.state === 'queued' ? 'Waiting for a worker…' : (r.stage ?? 'starting')}</span>
              {r.progress_total > 0 && (
                <span className="text-muted-foreground">
                  {r.progress_done}/{r.progress_total}
                </span>
              )}
            </div>
            <Progress value={percent} aria-label="Run progress" />
          </CardContent>
        </Card>
      )}

      {r.error && (
        <Alert variant="destructive">
          <AlertTitle>The run {r.state}</AlertTitle>
          <AlertDescription className="whitespace-pre-wrap">{r.error}</AlertDescription>
        </Alert>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Results{active && ' (partial)'}</CardTitle>
        </CardHeader>
        <CardContent>
          <ProblemAlert error={results.error} />
          <Tabs defaultValue="best">
            <TabsList>
              <TabsTrigger value="best">Best values</TabsTrigger>
              <TabsTrigger value="all">All outcomes</TabsTrigger>
              <TabsTrigger value="timeline">Timeline</TabsTrigger>
            </TabsList>
            <TabsContent value="best" className="pt-2">
              {results.data ? <ResultsTable best={results.data.best} onOpen={openResult} /> : <Skeleton className="h-24" />}
            </TabsContent>
            <TabsContent value="all" className="pt-2">
              {results.data ? (
                <OutcomesMatrix results={results.data.results} onOpen={openResult} />
              ) : (
                <Skeleton className="h-24" />
              )}
            </TabsContent>
            <TabsContent value="timeline" className="pt-2">
              <ProblemAlert error={events.error} />
              {events.data ? <EventsTimeline events={events.data} /> : <Skeleton className="h-24" />}
            </TabsContent>
          </Tabs>
        </CardContent>
      </Card>

      {Object.keys(r.options).length > 0 && (
        <p className="text-xs text-muted-foreground">
          Options: <code>{JSON.stringify(r.options)}</code>
        </p>
      )}

      <FieldResultSheet
        runId={r.id}
        resultId={resultId}
        documentId={r.document_id}
        decompositionId={r.decomposition_id}
        onClose={closeResult}
        onOpen={openResult}
      />
    </div>
  )
}
