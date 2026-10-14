import { Link, Outlet } from 'react-router'
import { HealthIndicator } from '@/components/HealthIndicator'
import { Toaster } from '@/components/ui/sonner'

export function Layout() {
  return (
    <div className="min-h-screen">
      <header className="border-b">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-4 py-3">
          <Link to="/" className="font-semibold">
            ContractExtraction
          </Link>
          <HealthIndicator />
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-4 py-6">
        <Outlet />
      </main>
      <Toaster />
    </div>
  )
}

export function NotFound() {
  return (
    <div className="space-y-2">
      <h1 className="text-xl font-semibold">Page not found</h1>
      <Link to="/" className="underline">
        Back to documents
      </Link>
    </div>
  )
}
