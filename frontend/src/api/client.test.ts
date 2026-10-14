import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { problem, server } from '@/test/server'
import { api, ProblemError, unwrap } from './client'

describe('unwrap', () => {
  it('returns the data of a 2xx answer', async () => {
    server.use(http.get('*/api/v1/config/pipelines', () => HttpResponse.json([])))
    const { data, response } = await unwrap(api.GET('/api/v1/config/pipelines'))
    expect(data).toEqual([])
    expect(response.status).toBe(200)
  })

  it('turns problem+json into a ProblemError with the request id', async () => {
    server.use(http.get('*/api/v1/runs/:id', () => problem(404, 'Not Found', 'Run not found', 'rid-42')))
    const error = await unwrap(api.GET('/api/v1/runs/{run_id}', { params: { path: { run_id: 'x' } } })).catch((e) => e)
    expect(error).toBeInstanceOf(ProblemError)
    expect(error).toMatchObject({ status: 404, title: 'Not Found', detail: 'Run not found', requestId: 'rid-42' })
  })

  it('keeps validation errors', async () => {
    server.use(
      http.post('*/api/v1/documents/:id/runs', () =>
        HttpResponse.json(
          { title: 'Unprocessable Content', status: 422, detail: 'The request is not valid', errors: [{ loc: ['body', 'kind'], msg: 'bad' }] },
          { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
        ),
      ),
    )
    const error = await unwrap(
      api.POST('/api/v1/documents/{document_id}/runs', {
        params: { path: { document_id: 'd' } },
        body: { kind: 'full', reuse_calls: true, redecompose: false },
      }),
    ).catch((e) => e)
    expect(error.errors).toEqual([{ loc: ['body', 'kind'], msg: 'bad' }])
  })

  it('reports a network failure as status 0', async () => {
    server.use(http.get('*/api/v1/config/pipelines', () => HttpResponse.error()))
    const error = await unwrap(api.GET('/api/v1/config/pipelines')).catch((e) => e)
    expect(error).toBeInstanceOf(ProblemError)
    expect(error.status).toBe(0)
  })
})
