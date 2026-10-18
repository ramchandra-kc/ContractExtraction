import { http, HttpResponse } from 'msw'
import { setupServer } from 'msw/node'
import type { FormatOut, HealthOut } from '@/api/client'
import { groundTruth } from './fixtures'

const healthy: HealthOut = { status: 'ok', components: [{ name: 'database', ok: true, detail: '' }] }
const formats: FormatOut[] = [
  { format: 'pdf', mime_types: ['application/pdf'], extensions: ['.pdf'] },
  { format: 'html', mime_types: ['text/html'], extensions: ['.htm', '.html'] },
]

/**
 * Requests without a handler fail the test; each test adds what it needs with server.use().
 * Defaults cover what the layout, the upload box and the document page always load.
 */
export const server = setupServer(
  http.get('*/api/v1/health/ready', () => HttpResponse.json(healthy)),
  http.get('*/api/v1/config/formats', () => HttpResponse.json(formats)),
  http.get('*/api/v1/documents/:id/ground-truth', () => HttpResponse.json(groundTruth)),
)

export function problem(status: number, title: string, detail?: string, requestId = 'rid-test') {
  return HttpResponse.json(
    { type: 'about:blank', title, status, ...(detail ? { detail } : {}) },
    { status, headers: { 'Content-Type': 'application/problem+json', 'X-Request-ID': requestId } },
  )
}
