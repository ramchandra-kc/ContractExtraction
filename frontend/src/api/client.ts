import createClient from 'openapi-fetch'
import type { components, paths } from './schema'

export type Schemas = components['schemas']
export type DocumentOut = Schemas['DocumentOut']
export type DocumentDetail = Schemas['DocumentDetail']
export type RunSummary = Schemas['RunSummary']
export type RunOut = Schemas['RunOut']
export type RunCreate = Schemas['RunCreate']
export type RunResults = Schemas['RunResults']
export type BestValue = Schemas['BestValue']
export type FieldResultOut = Schemas['FieldResultOut']
export type FieldResultDetail = Schemas['FieldResultDetail']
export type EventOut = Schemas['EventOut']
export type PipelineOut = Schemas['PipelineOut']
export type PagesOut = Schemas['PagesOut']
export type HealthOut = Schemas['HealthOut']

export const API = '/api/v1'

/**
 * Same-origin client: every request goes to /api/v1 on the page's own origin (the Vite proxy forwards it
 * to the gateway). fetch is looked up per call so test interceptors installed later still apply.
 */
export const api = createClient<paths>({
  baseUrl: typeof window === 'undefined' ? '' : window.location.origin,
  fetch: (request) => globalThis.fetch(request),
})

export interface ProblemFieldError {
  loc: (string | number)[]
  msg: string
  type?: string
}

/** An RFC 9457 problem (from the API or the gateway), or a network failure (status 0). */
export class ProblemError extends Error {
  readonly status: number
  readonly title: string
  readonly detail?: string
  readonly errors: ProblemFieldError[]
  readonly requestId?: string

  constructor(init: { status: number; title: string; detail?: string; errors?: ProblemFieldError[]; requestId?: string }) {
    super(init.detail ?? init.title)
    this.name = 'ProblemError'
    this.status = init.status
    this.title = init.title
    this.detail = init.detail
    this.errors = init.errors ?? []
    this.requestId = init.requestId
  }

  static from(response: Response, body: unknown): ProblemError {
    const p = (body && typeof body === 'object' ? body : {}) as Record<string, unknown>
    return new ProblemError({
      status: response.status,
      title: typeof p.title === 'string' ? p.title : response.statusText || `HTTP ${response.status}`,
      detail: typeof p.detail === 'string' ? p.detail : typeof body === 'string' && body ? body : undefined,
      errors: Array.isArray(p.errors) ? (p.errors as ProblemFieldError[]) : undefined,
      requestId: response.headers.get('X-Request-ID') ?? undefined,
    })
  }
}

interface FetchResult<T> {
  data?: T
  error?: unknown
  response: Response
}

/** Await an openapi-fetch call: the data, or a ProblemError for any non-2xx answer or network failure. */
export async function unwrap<T>(call: Promise<FetchResult<T>>): Promise<{ data: T; response: Response }> {
  let result: FetchResult<T>
  try {
    result = await call
  } catch (e) {
    throw new ProblemError({ status: 0, title: 'Network error', detail: e instanceof Error ? e.message : String(e) })
  }
  if (!result.response.ok) throw ProblemError.from(result.response, result.error)
  return { data: result.data as T, response: result.response }
}

export const documentFileUrl = (documentId: string) => `${API}/documents/${documentId}/file`
