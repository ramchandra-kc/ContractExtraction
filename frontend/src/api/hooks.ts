import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query'
import { config } from '@/lib/config'
import {
  api,
  ProblemError,
  unwrap,
  type DocumentOut,
  type EventOut,
  type HealthOut,
  type RunCreate,
  type RunOut,
} from './client'

/** queued and running, mirroring RunState.is_active in the backend. */
export const isActive = (state: string | undefined | null) => state === 'queued' || state === 'running'

export const keys = {
  health: ['health'] as const,
  pipelines: ['pipelines'] as const,
  catalog: ['catalog'] as const,
  documents: (limit: number, offset: number) => ['documents', { limit, offset }] as const,
  documentsAll: ['documents'] as const,
  document: (id: string) => ['document', id] as const,
  pages: (id: string, decompositionId?: string) => ['pages', id, decompositionId ?? 'latest'] as const,
  groundTruth: (documentId: string) => ['groundTruth', documentId] as const,
  run: (id: string) => ['run', id] as const,
  events: (id: string) => ['run', id, 'events'] as const,
  results: (id: string) => ['run', id, 'results'] as const,
  fieldResult: (runId: string, resultId: string) => ['run', runId, 'result', resultId] as const,
}

const poll = (active: boolean) => (active ? config.pollMs : false)

// ---- system ----------------------------------------------------------------------------------

/** Readiness: 503 still carries the components; a gateway problem (e.g. 502) becomes one failed component. */
export function useHealth() {
  return useQuery({
    queryKey: keys.health,
    queryFn: async (): Promise<HealthOut> => {
      try {
        const { data, error, response } = await api.GET('/api/v1/health/ready')
        if (response.ok && data) return data
        if (response.status === 503 && error && typeof error === 'object' && 'components' in error) return error as HealthOut
        const problem = ProblemError.from(response, error)
        return { status: 'degraded', components: [{ name: 'api', ok: false, detail: problem.detail ?? problem.title }] }
      } catch (e) {
        return { status: 'degraded', components: [{ name: 'gateway', ok: false, detail: e instanceof Error ? e.message : String(e) }] }
      }
    },
    refetchInterval: config.healthPollMs,
  })
}

// ---- config ----------------------------------------------------------------------------------

export function usePipelines() {
  return useQuery({
    queryKey: keys.pipelines,
    queryFn: async () => (await unwrap(api.GET('/api/v1/config/pipelines'))).data,
    staleTime: 60_000,
  })
}

// ---- documents -------------------------------------------------------------------------------

export function useDocuments(limit: number, offset: number) {
  return useQuery({
    queryKey: keys.documents(limit, offset),
    queryFn: async () => (await unwrap(api.GET('/api/v1/documents', { params: { query: { limit, offset } } }))).data,
    placeholderData: keepPreviousData,
    refetchInterval: (q) => poll(!!q.state.data?.items.some((d) => isActive(d.latest_run?.state))),
  })
}

export function useDocument(id: string | undefined) {
  return useQuery({
    queryKey: keys.document(id ?? ''),
    queryFn: async () =>
      (await unwrap(api.GET('/api/v1/documents/{document_id}', { params: { path: { document_id: id! } } }))).data,
    enabled: !!id,
    refetchInterval: (q) => poll(isActive(q.state.data?.latest_run?.state)),
  })
}

export function usePages(id: string, decompositionId?: string) {
  return useQuery({
    queryKey: keys.pages(id, decompositionId),
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/documents/{document_id}/pages', {
            params: { path: { document_id: id }, query: decompositionId ? { decomposition_id: decompositionId } : {} },
          }),
        )
      ).data,
    staleTime: Infinity, // a decomposition never changes
  })
}

export function useUploadDocument() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (file: File): Promise<{ document: DocumentOut; created: boolean }> => {
      const { data, response } = await unwrap(
        api.POST('/api/v1/documents', {
          body: { file: file as unknown as string },
          bodySerializer: () => {
            const form = new FormData()
            form.append('file', file)
            return form
          },
        }),
      )
      return { document: data, created: response.status === 201 }
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.documentsAll }),
  })
}

export function useCreateRun(documentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (body: RunCreate) =>
      (await unwrap(api.POST('/api/v1/documents/{document_id}/runs', { params: { path: { document_id: documentId } }, body })))
        .data,
    onSuccess: (run) => qc.setQueryData(keys.run(run.id), run),
    // On success and on 409 (another run is active), the document's latest run changed.
    onSettled: () => {
      qc.invalidateQueries({ queryKey: keys.document(documentId) })
      qc.invalidateQueries({ queryKey: keys.documentsAll })
    },
  })
}

// ---- ground truth ----------------------------------------------------------------------------

/** Labels of the default pipeline's field set for a document (unlabelled fields included). */
export function useGroundTruth(documentId: string) {
  return useQuery({
    queryKey: keys.groundTruth(documentId),
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/documents/{document_id}/ground-truth', { params: { path: { document_id: documentId } } }),
        )
      ).data,
  })
}

/** A label changes the document's labels and the evaluation shown in any run's results. */
function refreshLabels(qc: QueryClient, documentId: string) {
  qc.invalidateQueries({ queryKey: keys.groundTruth(documentId) })
  qc.invalidateQueries({ predicate: (q) => q.queryKey[0] === 'run' && q.queryKey[2] === 'results' })
}

export function useSetGroundTruth(documentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async ({ fieldId, value, notes }: { fieldId: string; value: unknown; notes?: string | null }) =>
      (
        await unwrap(
          api.PUT('/api/v1/documents/{document_id}/ground-truth/{field_id}', {
            params: { path: { document_id: documentId, field_id: fieldId } },
            body: { expected_value: value, notes: notes || null },
          }),
        )
      ).data,
    onSuccess: () => refreshLabels(qc, documentId),
  })
}

export function useDeleteGroundTruth(documentId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (fieldId: string) => {
      await unwrap(
        api.DELETE('/api/v1/documents/{document_id}/ground-truth/{field_id}', {
          params: { path: { document_id: documentId, field_id: fieldId } },
        }),
      )
    },
    onSuccess: () => refreshLabels(qc, documentId),
  })
}

// ---- runs ------------------------------------------------------------------------------------

function refreshFinishedRun(qc: QueryClient, run: RunOut) {
  qc.invalidateQueries({ queryKey: keys.events(run.id) })
  qc.invalidateQueries({ queryKey: keys.results(run.id) })
  qc.invalidateQueries({ queryKey: keys.document(run.document_id) })
  qc.invalidateQueries({ queryKey: keys.documentsAll })
}

/** Polls while the run is active; when it finishes, its events, results and document are fetched once more. */
export function useRun(id: string) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: keys.run(id),
    queryFn: async () => {
      const before = qc.getQueryData<RunOut>(keys.run(id))
      const run = (await unwrap(api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: id } } }))).data
      if (before && isActive(before.state) && !isActive(run.state)) refreshFinishedRun(qc, run)
      return run
    },
    refetchInterval: (q) => poll(isActive(q.state.data?.state)),
  })
}

/** The timeline, fetched incrementally with ?after=<last id>. */
export function useRunEvents(id: string, active: boolean) {
  const qc = useQueryClient()
  return useQuery({
    queryKey: keys.events(id),
    queryFn: async () => {
      const previous = qc.getQueryData<EventOut[]>(keys.events(id)) ?? []
      const after = previous.at(-1)?.id
      const fresh = (
        await unwrap(
          api.GET('/api/v1/runs/{run_id}/events', {
            params: { path: { run_id: id }, query: after === undefined ? {} : { after } },
          }),
        )
      ).data
      return fresh.length ? [...previous, ...fresh] : previous
    },
    refetchInterval: poll(active),
  })
}

/** Best values and every outcome; partial while the run is active. */
export function useRunResults(id: string, active: boolean) {
  return useQuery({
    queryKey: keys.results(id),
    queryFn: async () => (await unwrap(api.GET('/api/v1/runs/{run_id}/results', { params: { path: { run_id: id } } }))).data,
    refetchInterval: poll(active),
  })
}

export function useFieldResult(runId: string, resultId: string | null) {
  return useQuery({
    queryKey: keys.fieldResult(runId, resultId ?? ''),
    queryFn: async () =>
      (
        await unwrap(
          api.GET('/api/v1/runs/{run_id}/results/{field_result_id}', {
            params: { path: { run_id: runId, field_result_id: resultId! } },
          }),
        )
      ).data,
    enabled: !!resultId,
  })
}

export function useCancelRun() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: async (id: string) =>
      (await unwrap(api.POST('/api/v1/runs/{run_id}/cancel', { params: { path: { run_id: id } } }))).data,
    onSuccess: (run) => {
      qc.setQueryData(keys.run(run.id), run)
      if (!isActive(run.state)) refreshFinishedRun(qc, run)
    },
  })
}
