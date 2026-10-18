import { screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { document, documentDetail, DOC_ID } from '@/test/fixtures'
import { renderApp } from '@/test/render'
import { problem, server } from '@/test/server'

const pdf = () => new File(['%PDF-1.7'], 'sample.pdf', { type: 'application/pdf' })

function documentsApi(upload: Parameters<typeof http.post>[1]) {
  server.use(
    http.get('*/api/v1/documents', () => HttpResponse.json({ items: [document()], total: 1, limit: 25, offset: 0 })),
    http.post('*/api/v1/documents', upload),
    http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail())),
  )
}

describe('DocumentsPage', () => {
  it('lists documents', async () => {
    documentsApi(() => HttpResponse.json(document(), { status: 201 }))
    renderApp('/')
    expect(await screen.findByText('DOC001')).toBeInTheDocument()
    expect(screen.getByText('sample.pdf')).toBeInTheDocument()
    expect(screen.getByText('pdf')).toBeInTheDocument()
  })

  it('accepts the formats the API supports', async () => {
    documentsApi(() => HttpResponse.json(document(), { status: 201 }))
    renderApp('/')
    expect(await screen.findByText('.pdf, .htm, .html')).toBeInTheDocument()
    expect(screen.getByLabelText('Contract file')).toHaveAttribute(
      'accept',
      'application/pdf,.pdf,text/html,.htm,.html',
    )
  })

  it('opens a newly uploaded document (201)', async () => {
    // Only the header is checked: under jsdom, Node's fetch cannot stream a jsdom FormData body.
    let contentType: string | null = null
    documentsApi(({ request }) => {
      contentType = request.headers.get('content-type')
      return HttpResponse.json(document(), { status: 201 })
    })
    const { router } = renderApp('/')
    await userEvent.upload(screen.getByLabelText('Contract file'), pdf())

    await waitFor(() => expect(router.state.location.pathname).toBe(`/documents/${DOC_ID}`))
    expect(contentType).toMatch(/^multipart\/form-data; boundary=/)
    expect(await screen.findByText('Uploaded DOC001')).toBeInTheDocument()
  })

  it('opens the existing document when the file was uploaded before (200)', async () => {
    documentsApi(() => HttpResponse.json(document(), { status: 200 }))
    const { router } = renderApp('/')
    await userEvent.upload(screen.getByLabelText('Contract file'), pdf())

    await waitFor(() => expect(router.state.location.pathname).toBe(`/documents/${DOC_ID}`))
    expect(await screen.findByText('Already uploaded as DOC001')).toBeInTheDocument()
  })

  it.each([
    [413, 'Content Too Large', 'The upload is larger than 50 MB'],
    [422, 'Unprocessable Content', 'Unsupported file type; accepted: .pdf'],
  ])('shows the problem of a rejected upload (%i)', async (status, title, detail) => {
    documentsApi(() => problem(status, title, detail))
    const { router } = renderApp('/')
    await userEvent.upload(screen.getByLabelText('Contract file'), pdf())

    expect(await screen.findByRole('alert')).toHaveTextContent(`${status} ${title}`)
    expect(screen.getByRole('alert')).toHaveTextContent(detail)
    expect(router.state.location.pathname).toBe('/')
  })
})
