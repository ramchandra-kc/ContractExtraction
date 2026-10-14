/** An extracted value of any shape: text, number, boolean, list or object. */
export function JsonValue({ value }: { value: unknown }) {
  if (value === null || value === undefined || value === '') return <span className="text-muted-foreground">—</span>
  if (typeof value === 'string') return <span className="whitespace-pre-wrap">{value}</span>
  if (typeof value === 'number' || typeof value === 'boolean') return <span>{String(value)}</span>
  if (Array.isArray(value) && value.every((v) => typeof v !== 'object' || v === null)) {
    return (
      <ul className="list-disc pl-4">
        {value.map((v, i) => (
          <li key={i}>{String(v)}</li>
        ))}
      </ul>
    )
  }
  return <pre className="text-xs whitespace-pre-wrap">{JSON.stringify(value, null, 2)}</pre>
}
