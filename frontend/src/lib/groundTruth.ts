/**
 * Editing a ground-truth label. Labels are any JSON value except null; "" means "not in this contract".
 * The server checks a label against the field's JSON Schema. The editor has three shapes (editorKind):
 * a list of texts is one item per line, structured values (objects, lists of objects, numbers, booleans,
 * money) are JSON, everything else is text.
 */

type Schema = Record<string, unknown>

const schemaType = (schema?: Schema) => {
  const t = schema?.type
  return Array.isArray(t) ? t.find((x) => x !== 'null') : t
}

/** The editor shape for a field: by its JSON Schema when known, else by its coarse value type. */
export function editorKind(valueType: string, schema?: Schema): 'text' | 'list' | 'json' {
  const t = schemaType(schema)
  if (t === 'array') return schemaType(schema?.items as Schema) === 'string' ? 'list' : 'json'
  if (t === 'object' || t === 'boolean' || t === 'number' || t === 'integer') return 'json'
  if (t === 'string') return 'text'
  if (valueType === 'list') return 'list'
  return ['json', 'money', 'number', 'boolean'].includes(valueType) ? 'json' : 'text'
}

/** An example JSON value with the schema's shape (keys of objects, one item of lists), for the input hint. */
export function exampleFor(schema?: Schema): unknown {
  if (!schema) return undefined
  if (Array.isArray(schema.enum)) return schema.enum.join(' | ')
  const t = schemaType(schema)
  if (t === 'object') {
    const props = (schema.properties ?? {}) as Record<string, Schema>
    return Object.fromEntries(Object.entries(props).map(([k, v]) => [k, exampleFor(v) ?? null]))
  }
  if (t === 'array') return [exampleFor(schema.items as Schema) ?? '…']
  if (t === 'boolean') return true
  if (t === 'number' || t === 'integer') return 0
  return t === 'string' ? '…' : undefined
}

export interface LabelDraft {
  absent: boolean
  text: string
}

export type LabelParse = { ok: true; value: unknown } | { ok: false; error: string }

/** "" is the stored form of "not in this contract". */
export const isAbsent = (value: unknown) => value === ''

/** Editor state for an existing label, or for a value to start from (e.g. the extracted one). */
export function toDraft(value: unknown, valueType: string): LabelDraft {
  if (value === null || value === undefined) return { absent: false, text: '' }
  if (isAbsent(value)) return { absent: true, text: '' }
  if (valueType === 'list' && Array.isArray(value)) return { absent: false, text: value.map(String).join('\n') }
  if (typeof value === 'string') return { absent: false, text: value }
  return { absent: false, text: JSON.stringify(value, null, 2) }
}

/** Start from a run's best value: a field the run did not find starts as "not in this contract". */
export function draftFromOutcome(status: string, value: unknown, valueType: string): LabelDraft {
  return status === 'extracted' ? toDraft(value, valueType) : { absent: true, text: '' }
}

export function fromDraft(draft: LabelDraft, valueType: string): LabelParse {
  if (draft.absent) return { ok: true, value: '' }
  const text = draft.text.trim()
  if (!text) return { ok: false, error: 'Enter a value, or mark it as not in this contract.' }
  if (valueType === 'list') {
    return { ok: true, value: text.split('\n').map((line) => line.trim()).filter(Boolean) }
  }
  if (valueType === 'json') {
    try {
      const value: unknown = JSON.parse(text)
      return value === null ? { ok: false, error: 'null is not a label.' } : { ok: true, value }
    } catch {
      return { ok: false, error: 'Not valid JSON.' }
    }
  }
  return { ok: true, value: text }
}

/** Input hint per editor kind (see editorKind), with the expected shape when the schema is known. */
export function hintFor(kind: string, schema?: Schema): string {
  if (kind === 'list') return 'One item per line.'
  if (kind === 'json') {
    const example = exampleFor(schema)
    return example === undefined
      ? 'A JSON value.'
      : `JSON shaped like ${JSON.stringify(example)}. Leave out or null what the contract does not state.`
  }
  if (Array.isArray(schema?.enum)) return `One of: ${schema.enum.join(', ')}.`
  return 'Compared as trimmed, case-insensitive text with the best value.'
}
