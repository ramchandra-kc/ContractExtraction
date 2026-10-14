/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_POLL_MS?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
