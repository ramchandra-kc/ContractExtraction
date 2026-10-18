/** Runtime settings from VITE_* variables. Mutable so tests can poll faster. */
export const config = {
  pollMs: Number(import.meta.env.VITE_POLL_MS) || 5000,
  healthPollMs: 30_000,
}
