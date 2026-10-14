/**
 * Editing a ground-truth label. Labels are any JSON value except null; "" means "not in this contract".
 * Extracted values are not typed by value_type, so only list and json fields get a special shape:
 * a list is one item per line, json is parsed. Everything else is stored as text.
 */

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

/** Input hint per value type. */
export function hintFor(valueType: string): string {
  if (valueType === 'list') return 'One item per line.'
  if (valueType === 'json') return 'A JSON value.'
  return 'Compared as trimmed, case-insensitive text with the best value.'
}
