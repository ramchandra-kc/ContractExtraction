import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { FieldResultDetail } from '@/api/client'
import { useFieldResult } from '@/api/hooks'
import { JsonValue } from '@/components/JsonValue'
import { ProblemAlert } from '@/components/ProblemAlert'
import { VerdictBadge } from '@/components/VerdictBadge'
import { Badge } from '@/components/ui/badge'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { Skeleton } from '@/components/ui/skeleton'
import { formatDateTime, formatMs } from '@/lib/format'

interface Props {
  runId: string
  resultId: string | null
  /** Where evidence page links point: the run's document and decomposition. */
  documentId: string
  decompositionId: string | null
  onClose: () => void
  onOpen: (fieldResultId: string) => void
}

/** One outcome in full: value, judgements, evidence chunks and every LLM call. */
export function FieldResultSheet({ runId, resultId, documentId, decompositionId, onClose, onOpen }: Props) {
  const { data, error, isPending } = useFieldResult(runId, resultId)
  return (
    <Sheet open={!!resultId} onOpenChange={(open) => !open && onClose()}>
      <SheetContent className="w-full overflow-y-auto sm:max-w-2xl">
        <SheetHeader>
          <SheetTitle>{data ? data.field_label : 'Field result'}</SheetTitle>
          <SheetDescription>
            {data ? `${data.retrieval_config} · ${data.status.replace('_', ' ')}` : 'Loading…'}
          </SheetDescription>
        </SheetHeader>
        <div className="space-y-6 px-4 pb-6">
          <ProblemAlert error={error} />
          {isPending && resultId && <Skeleton className="h-48" />}
          {data && (
            <Detail
              data={data}
              pageLink={(page) =>
                `/documents/${documentId}/pages?page=${page}${decompositionId ? `&decomposition=${decompositionId}` : ''}`
              }
              onOpen={onOpen}
            />
          )}
        </div>
      </SheetContent>
    </Sheet>
  )
}

function Detail({
  data,
  pageLink,
  onOpen,
}: {
  data: FieldResultDetail
  pageLink: (page: number) => string
  onOpen: (id: string) => void
}) {
  return (
    <>
      <Section title="Value">
        <JsonValue value={data.value} />
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <VerdictBadge verdict={data.verdict} issue={data.issue} />
          <span>extraction {formatMs(data.extraction_ms)}</span>
          {data.reused_from && (
            <button type="button" className="underline" onClick={() => onOpen(data.reused_from!)}>
              reused from an earlier outcome
            </button>
          )}
        </div>
        {data.error && <p className="text-sm text-red-700">{data.error}</p>}
      </Section>

      <Section title={`Judgements (${data.judgements.length})`}>
        {data.judgements.length === 0 && <Empty>Not judged.</Empty>}
        {data.judgements.map((j, i) => (
          <div key={i} className="space-y-1 rounded-md border p-3 text-sm">
            <div className="flex items-center justify-between gap-2">
              <VerdictBadge verdict={j.verdict} issue={j.issue} />
              <span className="text-xs text-muted-foreground">{formatDateTime(j.created_at)}</span>
            </div>
            {j.explanation && <p>{j.explanation}</p>}
          </div>
        ))}
      </Section>

      <Section title={`Evidence (${data.hits.length})`}>
        {data.hits.length === 0 && <Empty>No chunks were retrieved.</Empty>}
        {data.hits.map((h) => (
          <div key={h.chunk_id} className="space-y-1 rounded-md border p-3 text-sm">
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="secondary">#{h.rank}</Badge>
              <span>score {h.score.toFixed(3)}</span>
              <Link to={pageLink(h.page)} className="underline">
                page {h.page}
              </Link>
              {h.matched_query && <span>· “{h.matched_query}”</span>}
            </div>
            <details>
              <summary className="cursor-pointer line-clamp-3 whitespace-pre-wrap">{h.text}</summary>
              <p className="mt-2 whitespace-pre-wrap">{h.text}</p>
            </details>
          </div>
        ))}
      </Section>

      {data.raw_answer && (
        <Section title="Raw answer">
          <pre className="rounded-md bg-muted p-3 text-xs whitespace-pre-wrap">{data.raw_answer}</pre>
        </Section>
      )}

      <Section title={`LLM calls (${data.llm_calls.length})`}>
        {data.llm_calls.length === 0 && <Empty>No calls.</Empty>}
        {data.llm_calls.map((c) => (
          <details key={c.id} className="rounded-md border p-3 text-sm">
            <summary className="flex cursor-pointer flex-wrap items-center gap-2">
              <Badge variant="outline">{c.purpose}</Badge>
              <span className="font-mono text-xs">
                {c.model_name}@{c.provider_key}
              </span>
              <span className={c.status === 'ok' ? 'text-xs text-muted-foreground' : 'text-xs text-red-700'}>
                {c.status}
              </span>
              <span className="text-xs text-muted-foreground">
                {formatMs(c.latency_ms)}
                {c.prompt_tokens != null && ` · ${c.prompt_tokens}+${c.completion_tokens ?? 0} tokens`}
                {c.cost_usd != null && ` · $${c.cost_usd}`}
              </span>
            </summary>
            <div className="mt-3 space-y-3">
              {c.error && <p className="text-red-700">{c.error}</p>}
              <Prompt label="System prompt" text={c.system_prompt} />
              <Prompt label="User prompt" text={c.user_prompt} />
              <Prompt label="Response" text={c.response} />
              <Prompt label="Parameters" text={JSON.stringify(c.params, null, 2)} />
            </div>
          </details>
        ))}
      </Section>
    </>
  )
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h3 className="text-sm font-semibold">{title}</h3>
      {children}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="text-sm text-muted-foreground">{children}</p>
}

function Prompt({ label, text }: { label: string; text: string | null | undefined }) {
  if (!text) return null
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground">{label}</p>
      <pre className="max-h-80 overflow-auto rounded-md bg-muted p-2 text-xs whitespace-pre-wrap">{text}</pre>
    </div>
  )
}
