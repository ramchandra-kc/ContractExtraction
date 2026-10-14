/// <reference types="vitest/config" />
import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// The app only uses relative /api URLs. In development, Vite proxies them to the gateway
// (VITE_GATEWAY_URL from .env / .env.local); the backend's address is never known here.
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, import.meta.dirname)
  return {
    plugins: [react(), tailwindcss()],
    resolve: { alias: { '@': path.resolve(import.meta.dirname, 'src') } },
    server: {
      port: 5173,
      strictPort: true,
      proxy: { '/api': { target: env.VITE_GATEWAY_URL || 'http://127.0.0.1:8080', changeOrigin: false } },
    },
    test: {
      environment: 'jsdom',
      globals: true,
      setupFiles: ['src/test/setup.ts'],
      css: false,
    },
  }
})
