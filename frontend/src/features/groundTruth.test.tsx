import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import {
  documentDetail,
  DOC_ID,
  FIELD_CUSTOMER,
  FIELD_PARTIES,
  FIELD_PAYMENT,
  fieldResult,
  groundTruth,
  results,
  run,
  RUN_ID,
} from '@/test/fixtures'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

interface Put {
  fieldId: string
  body: { expected_value: unknown; notes: string | null }
}

/** Records PUT and DELETE calls on the ground-truth endpoints. */
function labelApi() {
  const puts: Put[] = []
  const deletes: string[] = []
  server.use(
    http.put('*/api/v1/documents/:id/ground-truth/:fieldId', async ({ params, request }) => {
      const body = (await request.json()) as Put['body']
      puts.push({ fieldId: params.fieldId as string, body })
      const item = groundTruth.items.find((i) => i.field_id === params.fieldId)!
      return HttpResponse.json({ ...item, ...body, updated_at: '2026-10-14T12:00:00Z' })
    }),
    http.delete('*/api/v1/documents/:id/ground-truth/:fieldId', ({ params }) => {
      deletes.push(params.fieldId as string)
      return new HttpResponse(null, { status: 204 })
    }),
  )
  return { puts, deletes }
}

describe('GroundTruthCard', () => {
  function render() {
    server.use(http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail())))
    renderApp(`/documents/${DOC_ID}`)
  }

  it('lists every field with its label', async () => {
    render()
    expect(await screen.findByText(/contract_fields v1 · 2 of 3 fields labelled/)).toBeInTheDocument()
    const parties = screen.getByRole('button', { name: 'Edit Parties' }).closest('tr')!
    expect(within(parties).getByText('Not in this contract')).toBeInTheDocument()
    const payment = screen.getByRole('button', { name: 'Edit Payment terms' }).closest('tr')!
    expect(within(payment).getByText('—')).toBeInTheDocument()
    expect(within(payment).queryByRole('button', { name: /Clear/ })).not.toBeInTheDocument()
  })

  it('saves a text label with notes', async () => {
    const { puts } = labelApi()
    render()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Payment terms' }))
    await userEvent.type(screen.getByLabelText('Expected value'), '  60 days ')
    await userEvent.type(screen.getByLabelText('Notes'), 'clause 4')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]).toEqual({ fieldId: FIELD_PAYMENT, body: { expected_value: '60 days', notes: 'clause 4' } })
    await waitFor(() => expect(screen.queryByLabelText('Expected value')).not.toBeInTheDocument())
  })

  it('turns a list field from absent into one item per line', async () => {
    const { puts } = labelApi()
    render()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Parties' }))
    const absent = screen.getByRole('switch', { name: 'Not in this contract' })
    expect(absent).toBeChecked()
    await userEvent.click(absent)
    await userEvent.type(screen.getByLabelText('Expected value'), 'Acme{enter}Contoso')
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(puts).toHaveLength(1))
    expect(puts[0]).toEqual({ fieldId: FIELD_PARTIES, body: { expected_value: ['Acme', 'Contoso'], notes: null } })
  })

  it('refuses an empty value', async () => {
    const { puts } = labelApi()
    render()
    await userEvent.click(await screen.findByRole('button', { name: 'Edit Payment terms' }))
    await userEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a value')
    expect(puts).toHaveLength(0)
  })

  it('clears a label', async () => {
    const { deletes } = labelApi()
    render()
    await userEvent.click(await screen.findByRole('button', { name: 'Clear Customer name' }))
    await waitFor(() => expect(deletes).toEqual([FIELD_CUSTOMER]))
  })
})

describe('labels on the run page', () => {
  function render(resultsData = results) {
    server.use(
      http.get('*/api/v1/runs/:id', () => HttpResponse.json(run())),
      http.get('*/api/v1/runs/:id/events', () => HttpResponse.json([])),
      http.get('*/api/v1/runs/:id/results', () => HttpResponse.json(resultsData)),
      http.get('*/api/v1/runs/:id/results/:rid', () => HttpResponse.json(fieldResult)),
      http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail())),
    )
    renderApp(`/runs/${RUN_ID}`)
  }

  it('shows the expected value, the match and the summary', async () => {
    render()
    expect(await screen.findByText(/labelled fields match/)).toHaveTextContent(
      'Ground truth: 1 of 1 labelled fields match (1 unlabelled).',
    )
    const customer = screen.getByRole('button', { name: 'Customer name' }).closest('tr')!
    expect(within(customer).getByText('acme gmbh')).toBeInTheDocument()
    expect(within(customer).getByLabelText('matches')).toBeInTheDocument()
    const payment = screen.getByRole('button', { name: 'Payment terms' }).closest('tr')!
    expect(within(payment).getByLabelText('not labelled')).toBeInTheDocument()
  })

  it('labels a field the run did not find as not in this contract', async () => {
    const { puts } = labelApi()
    render()
    await userEvent.click(await screen.findByRole('button', { name: 'Label Payment terms' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByRole('switch', { name: 'Not in this contract' })).toBeChecked()
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))

    await waitFor(() => expect(puts).toEqual([{ fieldId: FIELD_PAYMENT, body: { expected_value: '', notes: null } }]))
  })

  it('prefills an unlabelled field with the extracted value', async () => {
    const unlabelled = {
      ...results,
      best: results.best.map((b) => ({ ...b, expected_value: null, exact_match: null })),
      evaluation: { fields: 2, labelled: 0, matched: 0 },
    }
    render(unlabelled)
    expect(await screen.findByText(/No ground truth for these fields yet/)).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Label Customer name' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByLabelText('Expected value')).toHaveValue('Acme GmbH')
  })

  it('keeps the notes of an existing label', async () => {
    const { puts } = labelApi()
    render()
    await userEvent.click(await screen.findByRole('button', { name: 'Label Customer name' }))
    const dialog = await screen.findByRole('dialog')
    expect(await within(dialog).findByLabelText('Expected value')).toHaveValue('acme gmbh')
    expect(within(dialog).getByLabelText('Notes')).toHaveValue('from the preamble')
    await userEvent.click(within(dialog).getByRole('button', { name: 'Save' }))
    await waitFor(() =>
      expect(puts).toEqual([
        { fieldId: FIELD_CUSTOMER, body: { expected_value: 'acme gmbh', notes: 'from the preamble' } },
      ]),
    )
  })
})
