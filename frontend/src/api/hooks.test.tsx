import type { ReactNode } from 'react'
import { QueryClientProvider } from '@tanstack/react-query'
import { renderHook, waitFor } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { config } from '@/lib/config'
import { run, RUN_ID } from '@/test/fixtures'
import { testQueryClient } from '@/test/render'
import { server } from '@/test/server'
import type { EventOut } from './client'
import { useRun, useRunEvents } from './hooks'

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={testQueryClient()}>{children}</QueryClientProvider>
)

const sleep = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms))

const event = (id: number): EventOut => ({
  id,
  created_at: '2026-10-14T10:00:00Z',
  level: 'info',
  stage: 'extracting',
  message: `event ${id}`,
  data: {},
})

describe('run polling', () => {
  const original = config.pollMs
  beforeEach(() => {
    config.pollMs = 20
  })
  afterEach(() => {
    config.pollMs = original
  })

  it('polls while the run is active and stops once it finished', async () => {
    const states = ['queued', 'running', 'succeeded']
    let calls = 0
    server.use(
      http.get('*/api/v1/runs/:id', () => HttpResponse.json(run({ state: states[Math.min(calls++, states.length - 1)] }))),
      // Fetched once more when the run finishes.
      http.get('*/api/v1/runs/:id/events', () => HttpResponse.json([])),
      http.get('*/api/v1/runs/:id/results', () => HttpResponse.json({})),
      http.get('*/api/v1/documents/:id', () => HttpResponse.json({})),
    )
    const { result } = renderHook(() => useRun(RUN_ID), { wrapper })

    await waitFor(() => expect(result.current.data?.state).toBe('succeeded'))
    const afterFinish = calls
    await sleep(100)
    expect(calls).toBe(afterFinish)
    expect(afterFinish).toBe(3)
  })

  it('fetches events incrementally with ?after=<last id>', async () => {
    const afters: (string | null)[] = []
    server.use(
      http.get('*/api/v1/runs/:id/events', ({ request }) => {
        const after = new URL(request.url).searchParams.get('after')
        afters.push(after)
        if (after === null) return HttpResponse.json([event(1), event(2)])
        if (after === '2') return HttpResponse.json([event(3)])
        return HttpResponse.json([])
      }),
    )
    const { result } = renderHook(() => useRunEvents(RUN_ID, true), { wrapper })

    await waitFor(() => expect(result.current.data?.map((e) => e.id)).toEqual([1, 2, 3]))
    expect(afters.slice(0, 2)).toEqual([null, '2'])
    await waitFor(() => expect(afters).toContain('3'))
  })
})
