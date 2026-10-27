# Prompt: draft P1 ground truth with Claude Cowork

Give Cowork access to the `ContractExtraction` folder, then paste everything below the line.
The output goes to `test_data/labels/`, which is git-ignored (the labels contain real names from the contracts).
Every label is a **draft**: review it in the UI before it counts as ground truth.

---

You are drafting ground-truth labels for a contract extraction research project. Accuracy matters more than speed:
these labels will be used to score other models, so a wrong label is worse than a missing one.

## Inputs

- `test_data/<type>/`: 20 contracts per contract type, in `.htm`, `.pdf`, `.txt` or `.docx`. The folder name is the
  contract type key.
- `docs/contract_types_and_fields.md`: the field catalogue. Read its introduction first (priority, formats, field
  types, anchors), then the section for each contract type. Each field row gives its key, type, priority and meaning.

## Task

1. **Select 8 contracts per type** for every folder except `other/` (18 types, 144 contracts). Within a type, mix the
   formats where the folder has more than one (e.g. some `.htm`, some `.pdf`, a `.docx` or `.txt` if present), and
   otherwise take files in alphabetical order. Write the selection to `test_data/labels/selection.json` before
   labelling anything: `{"<type>": ["test_data/<type>/<file>", ...], ...}`. Don't change the selection afterwards.
2. **Label each selected contract** with every **P1** field of its contract type (as listed in that type's section
   of the catalogue), and nothing else.
3. **Write one JSON file per contract** to `test_data/labels/<type>/<file name>.json` (e.g.
   `test_data/labels/msa/msa_03_example.htm.json`), in the format below.
4. Work one type at a time. After each type, append a line to `test_data/labels/progress.md`: the type, the number of
   contracts done, and anything that was hard or ambiguous.

If you stop part-way, the next session continues from `progress.md` and skips contracts that already have a file.

## Output format

```json
{
  "file": "test_data/msa/msa_03_example.htm",
  "contract_types": ["msa"],
  "labelled_by": "claude-cowork",
  "fields": {
    "effective_date": {
      "value": {"date": "2019-03-01", "relative_to": null, "offset": null},
      "evidence": "This Agreement is effective as of March 1, 2019",
      "location": "Preamble",
      "confidence": "high",
      "note": ""
    },
    "liquidated_damages": {
      "value": "",
      "evidence": "",
      "location": "",
      "confidence": "high",
      "note": "No liquidated damages clause; section 12 limits liability only"
    }
  }
}
```

- `contract_types`: the folder's type, plus any other catalogue type the document clearly also is (e.g.
  `["msa", "sow"]` for an MSA with a statement of work attached). Use only these keys: nda, msa, sow, saas,
  employment, contractor, goods_purchase, supply_distribution, property_lease, equipment_lease, loan, ip_license,
  jv_partnership, share_asset_purchase, franchise, construction, dpa, amendment. Label P1 fields for the folder's
  type only.
- `fields`: one entry for **every** P1 field of the type, with no extra keys.
- `value`: follows the field's type exactly as the catalogue defines it (see the rules below).
- `evidence`: the shortest verbatim quote from the contract that supports the value, copied exactly. Several quotes
  are joined with ` … `. Empty only when the value is `""`.
- `location`: the section number and heading, or the page, e.g. `"§ 9.2 Termination for Convenience"`.
- `confidence`: `high` (stated plainly), `medium` (you had to combine clauses or interpret wording), `low` (unclear,
  or you're unsure the clause is the right one).
- `note`: why, for anything `medium` or `low`, and for every `""`. Otherwise empty.

## Value rules

- **Absent:** `""` (an empty string) means the contract does not contain this information. Use it only after
  searching the whole document, including schedules, exhibits and the signature page. Never use `null` for a whole
  field.
- **Inside objects:** a key whose information is not in the contract is `null`; the other keys are still filled in.
  Lists that have no items are `[]`.
- **Not in the file:** when the contract refers to a schedule, exhibit or other document that isn't included
  (e.g. "fees as set out in Exhibit B" with no Exhibit B), use `""` for a top-level field, or `null` for that key,
  and say so in `note`.
- **Dates:** a field of type `date` is a plain string, `"2019-03-01"`, never an object. Don't invent a day or month
  that isn't stated; leave the value `""` (or the key `null`) and explain in `note`. A `date` field stated only
  relative to an event ("12 months after Completion") is `""`, with the wording in `note`.
- **Relative dates:** only a field of type `relative_date` (such as `effective_date` in the example above) is an object:
  fill `date` when the text gives or implies a calendar date, otherwise `relative_to` (the event, e.g.
  `"completion"`) and `offset` (a duration).
- **Durations:** ISO 8601: `P30D`, `P3M`, `P2Y`, `PT72H`. "Thirty (30) days" → `P30D`; "one year" → `P1Y`.
  Business days: still `P10D`, with `"business days"` in `note`.
- **Money:** `{"amount": 250000, "currency": "USD"}`, a plain number without separators, and an ISO 4217 currency.
  Use the currency the contract states, or the currency clearly implied by `$` and the parties' country (note it).
  Recurring money also has `period` (hour, day, week, month, quarter, year).
- **Percent:** a number from 0 to 100 (`5` for 5%).
- **Jurisdictions:** ISO 3166: `US-DE`, `US-NY`, `GB`, `AU-NSW`, `CA-ON`.
- **Booleans:** `true` / `false` only when the contract decides it. If it is silent, `""`.
- **Enums:** only the values listed in the catalogue.
- **Text fields:** a short faithful summary or the key wording, not the whole clause.
- **Party references** (`party_refs`, `*_party_refs`): use the `id` values you assigned in `parties`, e.g.
  `"p1"`, `"p2"`, in the order the parties appear in the preamble.
- **Redacted or blank values** (`[***]`, `_______`): `""` with `"redacted"` or `"left blank"` in `note`.

## Rules

- Use only the text of the contract. Don't use outside knowledge about the companies, and don't guess typical values.
- When clauses conflict (e.g. a later amendment inside the same file), use the governing clause and say which in
  `note`.
- Read the whole contract before labelling its fields; many P1 values live in definitions, schedules or the
  signature page.
- Don't edit, move or rename anything in `test_data/` outside `test_data/labels/`.
- If a file can't be read (scanned image with no text, broken encoding), write its JSON with `"fields": {}` and the
  reason in a top-level `"skipped"` key, and move on.

## When you finish

Write `test_data/labels/summary.md` containing:
- the number of contracts labelled per type, and any that were skipped (with the reasons);
- for each type, the P1 fields that were most often `""` and those most often `medium` or `low` confidence;
- recurring ambiguities that the labelling guide should settle (for example, how to treat "business days", or
  renewals that are silent about notice periods).
