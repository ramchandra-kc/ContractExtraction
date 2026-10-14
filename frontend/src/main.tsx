import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { RouterProvider, createBrowserRouter } from 'react-router'
import { TooltipProvider } from '@/components/ui/tooltip'
import { createQueryClient } from '@/lib/queryClient'
import { routes } from '@/routes'
import './index.css'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={createQueryClient()}>
      <TooltipProvider>
        <RouterProvider router={createBrowserRouter(routes)} />
      </TooltipProvider>
    </QueryClientProvider>
  </StrictMode>,
)
