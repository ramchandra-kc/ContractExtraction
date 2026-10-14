import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it, vi } from 'vitest'
import { keys } from '@/api/hooks'
import { catalog } from '@/test/fixtures'
import { renderApp } from '@/test/render'
import { problem, server } from '@/test/server'

interface Call {
  method: string
  path: string
  body: unknown
}

/** Serves the catalog fixture and records every configuration write. */
function configApi(respond?: (call: Call) => Response | undefined) {
  const calls: Call[] = []
  const record = async ({ request }: { request: Request }) => {
    const text = await request.text()
    const call = { method: request.method, path: new URL(request.url).pathname, body: text ? JSON.parse(text) : null }
    calls.push(call)
    return respond?.(call) ?? HttpResponse.json({}, { status: request.method === 'POST' ? 201 : 200 })
  }
  server.use(
    http.get('*/api/v1/config/catalog', () => HttpResponse.json(catalog)),
    http.post('*/api/v1/config/*', record),
    http.patch('*/api/v1/config/*', record),
    http.delete('*/api/v1/config/*', async (info) => {
      const r = await record(info)
      return r.status === 200 ? new HttpResponse(null, { status: 204 }) : r
    }),
  )
  return calls
}

describe('ConfigPage', () => {
  it('lists pipelines with their RAG order and why one cannot run', async () => {
    configApi()
    renderApp('/config')
    const row = (await screen.findByRole('button', { name: 'Edit default' })).closest('tr')!
    expect(within(row).getByText('default', { selector: '[data-slot=badge]' })).toBeInTheDocument()
    expect(within(row).getByText('RAG01 → RAG02')).toBeInTheDocument()
    expect(screen.getByText(/Cannot run: Model 'llama3.1:8b' \(extraction\) is disabled/)).toBeInTheDocument()
    const broken = screen.getByRole('button', { name: 'Edit broken' }).closest('tr')!
    expect(within(broken).getByRole('button', { name: 'Make default' })).toBeDisabled()
  })

  it('saves a pipeline with its RAG configs in the chosen order', async () => {
    const calls = configApi()
    renderApp('/config')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit default' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Move RAG02 up' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Add RAG03' }))
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save pipeline' }))

    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'PATCH',
      path: '/api/v1/config/pipelines/default',
      body: {
        retrievals: ['RAG02', 'RAG01', 'RAG03'],
        extraction_prompt: { name: 'extraction_system', version: 1 },
        judge_prompt: { name: 'judge_system', version: 1 },
      },
    })
  })

  it('shows validation problems from the API in the form', async () => {
    configApi(() =>
      HttpResponse.json(
        { title: 'Unprocessable Content', status: 422, detail: 'The request is not valid', errors: [{ loc: ['body', 'score_threshold'], msg: 'Input should be less than or equal to 1' }] },
        { status: 422, headers: { 'Content-Type': 'application/problem+json' } },
      ),
    )
    renderApp('/config?tab=retrievals')
    await userEvent.click(await screen.findByRole('button', { name: 'New RAG config' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Name'), 'RAG08')
    await userEvent.clear(within(dialog).getByLabelText('Score threshold'))
    await userEvent.type(within(dialog).getByLabelText('Score threshold'), '1.5')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

    const alert = await within(dialog).findByRole('alert')
    expect(alert).toHaveTextContent('422 Unprocessable Content')
    expect(alert).toHaveTextContent('body.score_threshold: Input should be less than or equal to 1')
  })

  it('shows an in-use delete as a problem in place', async () => {
    const calls = configApi(({ method }) =>
      method === 'DELETE' ? problem(409, 'Conflict', 'It is in use: runs, results or other configuration still refer to it') : undefined,
    )
    renderApp('/config?tab=retrievals')
    await userEvent.click(await screen.findByRole('button', { name: 'Delete RAG01' }))
    await userEvent.click(screen.getByRole('button', { name: 'Confirm delete RAG01' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('It is in use')
    expect(calls).toEqual([{ method: 'DELETE', path: '/api/v1/config/retrievals/RAG01', body: null }])
  })

  it('saves a prompt as a new version', async () => {
    const calls = configApi()
    renderApp('/config?tab=prompts')
    await userEvent.click(await screen.findByRole('button', { name: 'New version of extraction_system' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Saves v2 and makes it active/)).toBeInTheDocument()
    await userEvent.type(within(dialog).getByLabelText('Prompt'), ' Be brief.')
    await userEvent.type(within(dialog).getByLabelText('Notes'), 'shorter')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save new version' }))

    await waitFor(() =>
      expect(calls).toEqual([
        {
          method: 'POST',
          path: '/api/v1/config/prompts/extraction_system/versions',
          body: { body: 'You are precise. Be brief.', notes: 'shorter' },
        },
      ]),
    )
  })

  it('edits a field and its queries, one per line', async () => {
    const calls = configApi()
    renderApp('/config?tab=fields')
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Customer name' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Expansion queries'), '{enter}{enter}client company')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save field' }))
    await waitFor(() => expect(calls).toHaveLength(1))
    expect(calls[0]).toMatchObject({
      method: 'PATCH',
      body: { label: 'Customer name', queries: ['customer', 'buyer', 'client company'], value_type: 'text' },
    })
  })

  it('refreshes the catalog and the new-run pipelines after a write', async () => {
    configApi()
    const { queryClient } = renderApp('/config?tab=retrievals')
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries')
    await userEvent.click(await screen.findByRole('button', { name: 'New RAG config' }))
    const dialog = await screen.findByRole('dialog')
    await userEvent.type(within(dialog).getByLabelText('Name'), 'RAG08')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Create' }))

    await waitFor(() => expect(invalidate).toHaveBeenCalledWith({ queryKey: keys.pipelines }))
    expect(invalidate).toHaveBeenCalledWith({ queryKey: keys.catalog })
  })
})
