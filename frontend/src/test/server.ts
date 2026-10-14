import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { HealthOut } from '@/api/client'
import { groundTruth } from './fixtures'

const healthy: HealthOut = { status: 'ok', components: [{ name: 'database', ok: true, detail: '' }] }

/**
 * Requests without a handler fail the test; each test adds what it needs with server.use().
 * Defaults cover what the layout and the document page always load.
 */
export const server = setupServer(
  http.get('*/api/v1/health/ready', () => HttpResponse.json(healthy)),
  http.get('*/api/v1/documents/:id/ground-truth', () => HttpResponse.json(groundTruth)),
)

export function problem(status: number, title: string, detail?: string, requestId = 'rid-test') {
  return HttpResponse.json(
    { type: 'about:blank', title, status, ...(detail ? { detail } : {}) },
    { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': requestId } },
  )
}
