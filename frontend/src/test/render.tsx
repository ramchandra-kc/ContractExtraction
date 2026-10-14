import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { RouterProvider, createMemoryRouter } from 'react-router'
import { TooltipProvider } from '@/components/ui/tooltip'
import { routes } from '@/routes'

export function testQueryClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })
}

/** Render the whole app (layout and routes) at a URL. */
export function renderApp(url: string) {
  const router = createMemoryRouter(routes, { initialEntries: [url] })
  const queryClient = testQueryClient()
  const view = render(
    <QueryClientProvider client={queryClient}>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </QueryClientProvider>,
  )
  return { ...view, router, queryClient }
}
