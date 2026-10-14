import { QueryClient } from '@tanstack/react-query'
import { ProblemError } from '@/api/client'

/** Client errors (4xx) are final; network and server errors are retried once. */
export function createQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        refetchOnWindowFocus: false,
        retry: (count, error) =>
          count < 1 && !(error instanceof ProblemError && error.status >= 400 && error.status < 500),
      },
    },
  })
}
