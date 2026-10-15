import { describe, expect, it } from 'vitest'
import { draftFromOutcome, editorKind, fromDraft, hintFor, toDraft } from './groundTruth'

describe('ground-truth drafts', () => {
  it('stores "not in this contract" as an empty string', () => {
    expect(fromDraft({ absent: true, text: 'ignored' }, 'text')).toEqual({ ok: true, value: '' })
    expect(toDraft('', 'text')).toEqual({ absent: true, text: '' })
  })

  it('keeps text as trimmed text for every non-list, non-json type', () => {
    for (const type of ['text', 'date', 'number', 'money', 'boolean']) {
      expect(fromDraft({ absent: false, text: '  30 days ' }, type)).toEqual({ ok: true, value: '30 days' })
    }
  })

  it('turns lines into a list and back', () => {
    expect(fromDraft({ absent: false, text: 'Acme\n\n  Contoso \n' }, 'list')).toEqual({ ok: true, value: ['Acme', 'Contoso'] })
    expect(toDraft(['Acme', 'Contoso'], 'list')).toEqual({ absent: false, text: 'Acme\nContoso' })
  })

  it('parses json and rejects invalid json or null', () => {
    expect(fromDraft({ absent: false, text: '{"amount": 5}' }, 'json')).toEqual({ ok: true, value: { amount: 5 } })
    expect(fromDraft({ absent: false, text: '{oops' }, 'json')).toMatchObject({ ok: false })
    expect(fromDraft({ absent: false, text: 'null' }, 'json')).toMatchObject({ ok: false })
    expect(toDraft({ amount: 5 }, 'json').text).toContain('"amount": 5')
  })

  it('requires a value unless it is marked absent', () => {
    expect(fromDraft({ absent: false, text: '   ' }, 'text')).toMatchObject({ ok: false })
  })

  it('picks the editor shape from the schema, else the value type', () => {
    expect(editorKind('text', { type: 'array', items: { type: 'string' } })).toBe('list')
    expect(editorKind('json', { type: 'array', items: { type: 'object' } })).toBe('json')
    expect(editorKind('text', { type: ['boolean', 'null'] })).toBe('json')
    expect(editorKind('text', { type: 'string', enum: ['mutual', 'one_way'] })).toBe('text')
    expect(editorKind('money')).toBe('json')
    expect(editorKind('list', {})).toBe('list')
    expect(editorKind('date')).toBe('text')
    expect(hintFor('text', { type: 'string', enum: ['mutual', 'one_way'] })).toBe('One of: mutual, one_way.')
  })

  it('starts from a run outcome', () => {
    expect(draftFromOutcome('extracted', 'Acme', 'text')).toEqual({ absent: false, text: 'Acme' })
    expect(draftFromOutcome('not_found', null, 'text')).toEqual({ absent: true, text: '' })
    expect(toDraft(null, 'text')).toEqual({ absent: false, text: '' })
  })
})
