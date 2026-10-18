import { screen } from '@testing-library/react'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import type { DocumentOut, PagesOut } from '@/api/client'
import { documentDetail, DOC_ID } from '@/test/fixtures'
import { renderApp } from '@/test/render'
import { server } from '@/test/server'

const pages: PagesOut = {
  decomposition_id: '00000000-0000-0000-0000-0000000000d1',
  pages: [
    {
      page_number: 1,
      text: 'The fee is $5,000.',
      text_format: 'md',
      header: null,
      footer: null,
      width: null,
      height: null,
      images: [],
    },
  ],
}

function pagesApi(doc: Partial<DocumentOut>) {
  server.use(
    http.get('*/api/v1/documents/:id', () => HttpResponse.json(documentDetail(doc))),
    http.get('*/api/v1/documents/:id/pages', () => HttpResponse.json(pages)),
  )
}

describe('PagesPage', () => {
  it('shows a PDF at the same page', async () => {
    pagesApi({ format: 'pdf', mime_type: 'application/pdf' })
    renderApp(`/documents/${DOC_ID}/pages`)
    expect(await screen.findByTitle('Original PDF')).toHaveAttribute('src', `/api/v1/documents/${DOC_ID}/file#page=1`)
    expect(screen.getByText('The fee is $5,000.')).toBeInTheDocument()
  })

  it('shows an image original', async () => {
    pagesApi({ format: 'image', mime_type: 'image/png' })
    renderApp(`/documents/${DOC_ID}/pages`)
    expect(await screen.findByAltText('Original')).toHaveAttribute('src', `/api/v1/documents/${DOC_ID}/file`)
  })

  it.each([
    ['image', 'image/tiff'],
    ['html', 'text/html'],
    ['docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'],
  ] as const)('offers a download for originals browsers cannot show (%s)', async (format, mime_type) => {
    pagesApi({ format, mime_type })
    renderApp(`/documents/${DOC_ID}/pages`)
    expect(await screen.findByText(`The original (${format}) can't be shown here; the extracted text is what the models read.`))
      .toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Open original' })).toHaveAttribute('href', `/api/v1/documents/${DOC_ID}/file`)
    expect(screen.queryByTitle('Original PDF')).not.toBeInTheDocument()
  })
})
