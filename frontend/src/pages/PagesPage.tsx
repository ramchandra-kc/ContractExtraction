import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Link, useParams, useSearchParams } from 'react-router'
import { documentFileUrl, type DocumentFormat, type DocumentOut, type PageOut, type PagesOut } from '@/api/client'
import { useDocument, usePages } from '@/api/hooks'
import { ProblemAlert } from '@/components/ProblemAlert'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { cn } from '@/lib/utils'

/** Decomposed page text (what the LLM saw) next to the original (for a PDF, at the same page). */
export function PagesPage() {
  const { id = '' } = useParams()
  const [params, setParams] = useSearchParams()
  const decompositionId = params.get('decomposition') ?? undefined
  const pages = usePages(id, decompositionId)
  const document = useDocument(id)

  const goTo = (n: number) => {
    const next = new URLSearchParams(params)
    next.set('page', String(n))
    setParams(next)
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        <Link to={`/documents/${id}`} className="underline-offset-4 hover:underline">
          {document.data ? `${document.data.code} · ${document.data.title || document.data.original_filename}` : 'Document'}
        </Link>{' '}
        · pages
      </p>
      <ProblemAlert error={pages.error} />
      {pages.isPending && <Skeleton className="h-96" />}
      {pages.data && (
        <Viewer
          documentId={id}
          original={document.data && originalKind(document.data)}
          data={pages.data}
          requested={Number(params.get('page')) || 1}
          onPage={goTo}
        />
      )}
    </div>
  )
}

/** How the original can be shown: browsers render PDFs and most images, but not TIFF scans, HTML (only sandboxed downloads) or Word. */
type OriginalKind = { show: 'pdf' | 'image' | 'download'; format: DocumentFormat }

function originalKind(doc: DocumentOut): OriginalKind {
  if (doc.format === 'pdf') return { show: 'pdf', format: doc.format }
  if (doc.format === 'image' && doc.mime_type !== 'image/tiff') return { show: 'image', format: doc.format }
  return { show: 'download', format: doc.format }
}

function Viewer({
  documentId,
  original,
  data,
  requested,
  onPage,
}: {
  documentId: string
  original: OriginalKind | undefined
  data: PagesOut
  requested: number
  onPage: (n: number) => void
}) {
  if (data.pages.length === 0) return <p className="text-sm text-muted-foreground">This decomposition has no pages.</p>
  const page = data.pages.find((p) => p.page_number === requested) ?? data.pages[0]

  return (
    <div className="grid gap-4 lg:grid-cols-[5rem_1fr_1fr]">
      <nav aria-label="Pages" className="flex gap-1 overflow-x-auto lg:max-h-[80vh] lg:flex-col lg:overflow-y-auto">
        {data.pages.map((p) => (
          <button
            key={p.page_number}
            type="button"
            onClick={() => onPage(p.page_number)}
            aria-current={p.page_number === page.page_number ? 'page' : undefined}
            className={cn(
              'rounded-md px-3 py-1 text-sm hover:bg-accent',
              p.page_number === page.page_number && 'bg-primary text-primary-foreground hover:bg-primary',
            )}
          >
            {p.page_number}
          </button>
        ))}
      </nav>

      <Card className="lg:max-h-[80vh] lg:overflow-y-auto">
        <CardContent className="space-y-3 pt-6">
          <h2 className="text-sm font-semibold">
            Page {page.page_number} · extracted text ({page.text_format})
          </h2>
          {page.header && <p className="border-b pb-2 text-xs text-muted-foreground">Header: {page.header}</p>}
          {page.text_format === 'md' ? (
            <div className="prose-page text-sm">
              <Markdown remarkPlugins={[remarkGfm]}>{page.text}</Markdown>
            </div>
          ) : (
            // Other formats are shown as source text; the page's HTML is never injected.
            <pre className="text-xs whitespace-pre-wrap">{page.text}</pre>
          )}
          {page.footer && <p className="border-t pt-2 text-xs text-muted-foreground">Footer: {page.footer}</p>}
          {page.images.length > 0 && (
            <div className="grid grid-cols-2 gap-2">
              {page.images.map((img) => (
                <img
                  key={img.id}
                  src={img.url}
                  alt={img.file_name}
                  loading="lazy"
                  className="rounded border"
                  width={img.width ?? undefined}
                  height={img.height ?? undefined}
                />
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      <Original documentId={documentId} original={original} page={page} />
    </div>
  )
}

/** The original next to the extracted text: the PDF at the same page, the image, or a download for other formats. */
function Original({ documentId, original, page }: { documentId: string; original: OriginalKind | undefined; page: PageOut }) {
  const url = documentFileUrl(documentId)
  if (original?.show === 'pdf') {
    // Keyed by page: changing only the #page fragment does not move every browser's PDF viewer.
    return (
      <iframe
        key={page.page_number}
        title="Original PDF"
        src={`${url}#page=${page.page_number}`}
        className="h-[80vh] w-full rounded-lg border"
      />
    )
  }
  if (original?.show === 'image') {
    return <img src={url} alt="Original" className="max-h-[80vh] w-full rounded-lg border object-contain" />
  }
  return (
    <Card>
      <CardContent className="space-y-2 pt-6 text-sm text-muted-foreground">
        <p>The original ({original?.format ?? 'file'}) can't be shown here; the extracted text is what the models read.</p>
        <a href={url} className="text-foreground underline underline-offset-4">
          Open original
        </a>
      </CardContent>
    </Card>
  )
}
