import { useState } from 'react'
import type { Catalog } from '@/api/config'
import { Badge } from '@/components/ui/badge'
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table'
import { SelectInput } from './form'

const GROUPS: Record<string, string> = {
  core: 'Core',
  commercial: 'Commercial',
  risk_liability: 'Risk & Liability',
  restrictive_covenants: 'Restrictive Covenants',
  ip_data: 'IP & Data',
  specific: 'Type-specific',
}

/** Contract types and the fields each expects (read-only: edited in docs/contract_types_and_fields.md). */
export function ContractTypesTab({ catalog }: { catalog: Catalog }) {
  const [selected, setSelected] = useState(0)
  const fieldSet = catalog.field_sets[selected]
  if (!fieldSet) return <p className="text-sm text-muted-foreground">No field sets.</p>
  const labels = new Map(fieldSet.fields.map((f) => [f.key, f.label]))
  return (
    <div className="space-y-3">
      {catalog.field_sets.length > 1 && (
        <div className="w-64">
          <SelectInput
            label="Field set"
            value={String(selected)}
            onChange={(v) => setSelected(Number(v))}
            options={catalog.field_sets.map((f, i) => ({ value: String(i), label: `${f.name} v${f.version}` }))}
          />
        </div>
      )}
      <p className="text-sm text-muted-foreground">
        A run detects the document&apos;s contract type(s) and extracts their fields; the fallback type covers documents
        matching none. Types and their fields are defined in <code>docs/contract_types_and_fields.md</code>: edit it, run{' '}
        <code>contract-extraction gen-catalogue</code> and recreate the database.
      </p>
      {fieldSet.contract_types.length === 0 ? (
        <p className="text-sm text-muted-foreground">This field set defines no contract types: runs extract all its fields.</p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Type</TableHead>
              <TableHead>Identify by</TableHead>
              <TableHead>Fields</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {fieldSet.contract_types.map((t) => {
              const count = (p: string) => t.fields.filter((f) => f.priority === p).length
              const groups = [...new Set(t.fields.map((f) => f.group))]
              return (
                <TableRow key={t.key} className="align-top">
                  <TableCell className="whitespace-normal">
                    <div className="flex items-center gap-2 font-medium">
                      {t.label}
                      {t.is_fallback && <Badge variant="secondary">fallback</Badge>}
                    </div>
                    <span className="font-mono text-xs text-muted-foreground">{t.key}</span>
                  </TableCell>
                  <TableCell className="max-w-sm text-xs whitespace-normal text-muted-foreground">{t.description}</TableCell>
                  <TableCell className="text-xs whitespace-normal">
                    <details>
                      <summary className="cursor-pointer">
                        {t.fields.length} fields · P1 {count('P1')} · P2 {count('P2')} · P3 {count('P3')}
                      </summary>
                      <div className="mt-2 space-y-2">
                        {groups.map((g) => (
                          <div key={g}>
                            <p className="font-medium">{GROUPS[g] ?? g}</p>
                            <ul className="flex flex-wrap gap-1">
                              {t.fields
                                .filter((f) => f.group === g)
                                .map((f) => (
                                  <li key={f.key}>
                                    <Badge variant={f.priority === 'P1' ? 'default' : 'outline'} title={`${f.key} · ${f.priority}`}>
                                      {labels.get(f.key) ?? f.key}
                                    </Badge>
                                  </li>
                                ))}
                            </ul>
                          </div>
                        ))}
                      </div>
                    </details>
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      )}
    </div>
  )
}
