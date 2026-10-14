/** Form values are kept as text; these turn them into what the API expects (blank → null). */
export const toInt = (s: string) => (s.trim() === '' ? null : Number(s.trim()))
export const toDecimal = (s: string) => (s.trim() === '' ? null : s.trim())
export const toText = (s: string) => (s.trim() === '' ? null : s.trim())
export const show = (v: unknown) => (v === null || v === undefined ? '' : String(v))
