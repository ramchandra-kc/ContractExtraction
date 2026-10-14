import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { documentDetail, DOC_ID, DEC_ID, fieldResult, RESULT_A, RESULT_C, results, run, RUN_ID } from '@/test/fixtures'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

function runApi() {
  server.use(
    http.get('*/api/v1/runs/:id', () => HttpResponse.json(run())),
    http.get('*/api/v1/runs/:id/events', () => HttpResponse.json([])),
    http.get('*/api/v1/runs/:id/results', () => HttpResponse.json(results)),
    http.get('*/api/v1/runs/:id/results/:rid', () => HttpResponse.json(fieldResult)),
    http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail())),
  )
}

describe('run results', () => {
  it('shows the best value per field with its verdict', async () => {
    runApi()
    renderApp(`/runs/${RUN_ID}`)
    const row = (await screen.findByRole('button', { name: 'Customer name' })).closest('tr')!
    expect(within(row).getByText('Acme GmbH')).toBeInTheDocument()
    expect(within(row).getByText('PASS')).toBeInTheDocument()
    expect(within(row).getByText('Named in the preamble.')).toBeInTheDocument()
    const missing = screen.getByRole('button', { name: 'Payment terms' }).closest('tr')!
    expect(within(missing).getByText('not found')).toBeInTheDocument()
  })

  it('shows every outcome as fields × RAG configs', async () => {
    runApi()
    const { router } = renderApp(`/runs/${RUN_ID}`)
    await userEvent.click(await screen.findByRole('tab', { name: 'All outcomes' }))

    const headers = screen.getAllByRole('columnheader').map((h) => h.textContent)
    expect(headers).toEqual(['Field', 'RAG01', 'RAG02'])
    const cell = screen.getByRole('button', { name: 'Customer name with RAG02' })
    expect(cell).toHaveTextContent('ACME')
    expect(cell).toHaveTextContent('FAIL · INCOMPLETE')

    await userEvent.click(cell)
    expect(router.state.location.search).toBe(`?result=${RESULT_C}`)
  })

  it('opens the evidence sheet with hits, judgements and LLM calls', async () => {
    runApi()
    renderApp(`/runs/${RUN_ID}?result=${RESULT_A}`)
    const sheet = await screen.findByRole('dialog')

    expect(await within(sheet).findByText('Evidence (1)')).toBeInTheDocument()
    expect(within(sheet).getByText('score 0.812')).toBeInTheDocument()
    expect(within(sheet).getByRole('link', { name: 'page 2' })).toHaveAttribute(
      'href',
      `/documents/${DOC_ID}/pages?page=2&decomposition=${DEC_ID}`,
    )
    expect(within(sheet).getByText('Judgements (1)')).toBeInTheDocument()
    expect(within(sheet).getByText('Supported by the evidence.')).toBeInTheDocument()
    expect(within(sheet).getByText('LLM calls (1)')).toBeInTheDocument()
    expect(within(sheet).getByText('llama3.1:8b@ollama-local')).toBeInTheDocument()
    expect(within(sheet).getByText(/812\+12 tokens/)).toBeInTheDocument()
  })
})
