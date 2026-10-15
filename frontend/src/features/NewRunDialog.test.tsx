import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { RunCreate } from '@/api/client'
import { documentDetail, DOC_ID, pipelines, run, RUN_ID, runSummary } from '@/test/fixtures'
import { renderApp } from '@/test/render'
import { problem, server } from '@/test/server'

const ACTIVE_RUN = '77777777-7777-7777-7777-777777777777'

describe('NewRunDialog', () => {
  it('detects the contract type by default', async () => {
    let body: RunCreate | null = null
    server.use(
      http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail())),
      http.get('*/api/v1/config/pipelines', () => HttpResponse.json(pipelines)),
      http.post('*/api/v1/documents/:id/runs', async ({ request }) => {
        body = (await request.json()) as RunCreate
        return problem(409, 'Conflict', 'stop here')
      }),
    )
    renderApp(`/documents/${DOC_ID}`)
    await userEvent.click(await screen.findByRole('button', { name: 'New run' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByRole('radio', { name: /Detect the contract type/ })).toBeChecked()
    expect(within(dialog).queryByRole('checkbox', { name: 'Payment terms' })).toBeNull()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Queue run' }))
    await waitFor(() => expect(body).toMatchObject({ fields: null, contract_types: null }))

    await userEvent.click(within(dialog).getByRole('radio', { name: /Contract types/ }))
    expect(within(dialog).getByRole('button', { name: 'Queue run' })).toBeDisabled()
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'MSA (2)' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Queue run' }))
    await waitFor(() => expect(body).toMatchObject({ fields: null, contract_types: ['msa'] }))
  })

  it('queues a run narrowed to the chosen fields and opens it', async () => {
    let body: RunCreate | null = null
    server.use(
      http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail())),
      http.get('*/api/v1/config/pipelines', () => HttpResponse.json(pipelines)),
      http.post('*/api/v1/documents/:id/runs', async ({ request }) => {
        body = (await request.json()) as RunCreate
        return HttpResponse.json(run({ state: 'queued' }), { status: 202 })
      }),
      http.get('*/api/v1/runs/:id', () => HttpResponse.json(run({ state: 'queued' }))),
      http.get('*/api/v1/runs/:id/events', () => HttpResponse.json([])),
      http.get('*/api/v1/runs/:id/results', () => HttpResponse.json({ run: run(), best: [], results: [] })),
    )
    const { router } = renderApp(`/documents/${DOC_ID}`)
    await userEvent.click(await screen.findByRole('button', { name: 'New run' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('radio', { name: /Fields…/ }))
    await userEvent.click(within(dialog).getByRole('checkbox', { name: 'Customer name' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Queue run' }))

    await waitFor(() => expect(router.state.location.pathname).toBe(`/runs/${RUN_ID}`))
    expect(body).toMatchObject({ pipeline: 'default', kind: 'full', fields: ['customer_name'], contract_types: null,
                                 retrievals: null, judge: null })
  })

  it('links the active run when the API answers 409', async () => {
    let posted = false
    server.use(
      // After the 409 the document is fetched again and shows the run that is now active.
      http.get('*/api/v1/documents/:id', () =>
        HttpResponse.json(
          documentDetail(posted ? { latest_run: runSummary({ id: ACTIVE_RUN, state: 'running', finished_at: null }) } : {}),
        ),
      ),
      http.get('*/api/v1/config/pipelines', () => HttpResponse.json(pipelines)),
      http.post('*/api/v1/documents/:id/runs', () => {
        posted = true
        return problem(409, 'Conflict', 'DOC001 already has an active run')
      }),
    )
    renderApp(`/documents/${DOC_ID}`)
    await userEvent.click(await screen.findByRole('button', { name: 'New run' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(await within(dialog).findByRole('button', { name: 'Queue run' }))

    expect(await within(dialog).findByRole('alert')).toHaveTextContent('409 Conflict')
    const link = await within(dialog).findByRole('link', { name: 'Open the active run' })
    expect(link).toHaveAttribute('href', `/runs/${ACTIVE_RUN}`)
  })
})
