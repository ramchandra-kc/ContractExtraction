import type { RouteObject } from 'react-router'
import { Layout, NotFound } from '@/components/Layout'
import { ConfigPage } from '@/pages/ConfigPage'
import { DocumentPage } from '@/pages/DocumentPage'
import { DocumentsPage } from '@/pages/DocumentsPage'
import { PagesPage } from '@/pages/PagesPage'
import { RunPage } from '@/pages/RunPage'

export const routes: RouteObject[] = [
  {
    element: <Layout />,
    children: [
      { path: '/', element: <DocumentsPage /> },
      { path: '/documents/:id', element: <DocumentPage /> },
      { path: '/documents/:id/pages', element: <PagesPage /> },
      { path: '/runs/:id', element: <RunPage /> },
      { path: '/config', element: <ConfigPage /> },
      { path: '*', element: <NotFound /> },
    ],
  },
]
