# Contract Types and Extraction Fields

Each section below is self-contained: it lists every field for that contract type, grouped by category. **Identify by** tells the classifier how to recognise the type. The fallback section **Other** lists its field groups by name (**Includes:**) instead of repeating them.

This file is the source of truth for the field catalogue: after editing it, run `uv run contract-extraction gen-catalogue` (in `backend/`) to regenerate `docker/seed_catalogue.sql`, then recreate the database.

**Priority:** P1 = direct financial, time or exit exposure (always report) · P2 = material risk · P3 = informational

**Formats:** dates `YYYY-MM-DD` (ISO 8601) · durations `P30D`, `P3Y`, `PT72H` (ISO 8601) · money = amount + ISO 4217 currency (+ period if recurring) · jurisdictions `AU-NSW`, `US-DE` (ISO 3166) · percent on a 0–100 scale

**Field types:**

| Type | Value |
|---|---|
| `string` | Short text, verbatim where possible |
| `text` | Free text: a summary or the clause wording |
| `strings` | List of short texts |
| `bool` | `true` / `false` |
| `int`, `number` | Number |
| `percent` | Number on a 0–100 scale |
| `date` | `YYYY-MM-DD` |
| `duration` | ISO 8601 duration, e.g. `P30D`, `P3Y`, `PT72H` |
| `relative_date` | object: date, relative_to, offset — `date` when the text gives or implies a calendar date; otherwise `relative_to` (the event, e.g. "completion") and `offset` (duration) |
| `money` | object: amount, currency |
| `recurring_money` | object: amount, currency, period (enum: hour, day, week, month, quarter, year) |
| `language` | ISO 639-1 code, e.g. `en` |
| `jurisdiction` | ISO 3166 code, e.g. `AU-NSW`, `US-NY`, `GB` |
| `jurisdictions` | List of `jurisdiction` |
| `party_refs` | List of party ids from `parties` |
| `restriction` | object: exists, restricted_party_refs, scope, territory, duration |
| `enum: a, b` | One of the listed values |
| `object: a, b` | Object with the listed keys |
| `list of: a, b` | List of objects with the listed keys |

A field key means the same thing in every contract type; only its priority may differ between types.

**Anchors:** fields that are almost always stated on the cover page or in the preamble (start), or on the signature page (end). Their evidence always includes the document's opening or closing chunks, besides the retrieved ones, when the RAG config enables anchors (`anchor_chunks`).

- **Anchor start:** title, parties, parent_agreement_ref, effective_date, language, amendment_number, sow_number, nda_direction, disclosing_party_refs, receiving_party_refs, guarantor_refs
- **Anchor end:** signatories, execution_date
- **Anchor both:** document_status

## Contents

1. [NDA](#1-nda)
2. [MSA](#2-msa)
3. [SOW](#3-sow)
4. [SaaS](#4-saas)
5. [Employment](#5-employment)
6. [Contractor](#6-contractor)
7. [Goods Purchase](#7-goods-purchase)
8. [Supply & Distribution](#8-supply--distribution)
9. [Property Lease](#9-property-lease)
10. [Equipment Lease](#10-equipment-lease)
11. [Loan](#11-loan)
12. [IP License](#12-ip-license)
13. [JV & Partnership](#13-jv--partnership)
14. [Share-Asset Purchase](#14-share-asset-purchase)
15. [Franchise](#15-franchise)
16. [Construction](#16-construction)
17. [DPA](#17-dpa)
18. [Amendment](#18-amendment)
19. [Other](#19-other) — fallback when no type above fits; reuses shared groups by name

---

## 1. NDA

**Identify by:** Non-disclosure or confidentiality agreement whose main purpose is protecting information disclosed between the parties, mutual or one-way.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### NDA-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `nda_direction` | enum: mutual, one_way | P1 | Whether one or both parties disclose |
| `disclosing_party_refs` | party_refs | P1 | Party id(s) disclosing |
| `receiving_party_refs` | party_refs | P1 | Party id(s) receiving |
| `permitted_purpose` | text | P1 | Only purpose the information may be used for |
| `confidential_info_definition` | text | P2 | What counts as confidential |
| `standard_exclusions` | strings | P3 | Public, already known, independently developed, etc. |
| `permitted_disclosees` | strings | P2 | Employees, advisers, affiliates, financiers |
| `confidentiality_period` | duration | P1 | How long obligations last |
| `trade_secrets_indefinite` | bool | P2 | Trade secrets protected while they remain secret |
| `return_or_destroy` | object: required, deadline, certification_required, archival_copies_allowed | P2 | Obligations on request or at end |
| `residuals_clause` | bool | P1 | Recipient may use information retained in memory (high risk for discloser) |
| `compelled_disclosure_procedure` | text | P3 | Steps if disclosure is legally required |
| `injunctive_relief` | bool | P3 | Express right to seek an injunction |

---

## 2. MSA

**Identify by:** Master or framework agreement setting general terms for future services or purchases; individual engagements are made by SOWs, work orders or purchase orders under it.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### MSA-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `affiliates_may_order` | bool | P2 | Affiliates can place orders under the MSA |
| `ordering_mechanism` | enum: sow, purchase_order, order_form, other | P3 | How engagements are created |
| `rate_card` | list of: role, rate | P1 | Standard rates for SOWs |
| `service_levels` | list of: metric, target, measurement_period, service_credit | P1 | Committed service levels and linked service credits |
| `service_credit_cap` | percent | P2 | Max service credits as % of fees |
| `acceptance_procedure` | object: acceptance_period, deemed_acceptance, rejection_cycles | P2 | How deliverables are accepted |
| `subcontracting` | enum: prohibited, consent_required, permitted, not_stated | P2 | Right to subcontract or use substitutes |
| `step_in_rights` | bool | P2 | Customer may take over services on failure |
| `benchmarking` | bool | P3 | Right to benchmark prices |

---

## 3. SOW

**Identify by:** Statement of work, work order or project schedule, usually under a master agreement, describing one project's scope, deliverables, milestones and fees.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### SOW-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `sow_number` | string | P3 | SOW identifier |
| `scope_of_work` | text | P1 | Services in scope |
| `out_of_scope` | strings | P2 | Explicit exclusions |
| `pricing_model` | enum: fixed_price, time_and_materials, capped_time_and_materials, retainer, outcome_based | P1 | How the work is charged |
| `not_to_exceed` | money | P1 | Fee ceiling |
| `deliverables` | list of: name, due_date, acceptance_criteria | P1 | What must be delivered and when |
| `milestones` | list of: name, due_date, payment | P1 | Milestones and linked payments |
| `key_personnel` | strings | P3 | Named individuals required |
| `client_dependencies` | strings | P2 | Customer obligations the supplier relies on |
| `change_request_process` | text | P2 | How scope changes are priced and approved |

---

## 4. SaaS

**Identify by:** Subscription to hosted software or cloud services: subscription fees, users or seats, uptime and service levels, customer data, support.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### SaaS-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `subscription_plan` | string | P2 | Plan or edition |
| `subscription_fee` | recurring_money | P1 | Recurring fee |
| `licensed_quantity` | object: metric, quantity | P1 | Units purchased |
| `overage_fees` | recurring_money | P1 | Charge per unit above licensed quantity |
| `uptime_commitment` | percent | P1 | Availability SLA, e.g. 99.9 |
| `service_levels` | list of: metric, target, measurement_period, service_credit | P2 | Committed service levels and linked service credits |
| `support_tier` | object: tier, hours, first_response_time | P2 | Support entitlement |
| `data_ownership` | enum: customer, provider, shared, not_stated | P1 | Who owns customer data |
| `data_residency` | jurisdictions | P2 | Where data is stored |
| `subprocessors` | strings | P3 | Named subprocessors or list URL |
| `security_certifications` | strings | P3 | e.g. ISO/IEC 27001, SOC 2 Type II |
| `data_export_on_exit` | object: available, window, format, chargeable | P1 | Retrieving data after termination |
| `data_deletion_period` | duration | P2 | When data is deleted after exit |
| `usage_restrictions` | strings | P3 | Prohibited uses |
| `suspension_rights` | text | P2 | When the provider may suspend service |

---

## 5. Employment

**Identify by:** Employment contract or offer letter between an employer and an individual employee: position, salary, hours, leave, notice.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### Employment-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `position_title` | string | P2 | Job title |
| `reporting_to` | string | P3 | Manager or role reported to |
| `employment_type` | enum: permanent_full_time, permanent_part_time, fixed_term, casual | P1 | Basis of employment |
| `work_location` | object: primary_location, arrangement | P3 | Where work is performed |
| `probation_period` | duration | P2 | Probation length |
| `base_salary` | recurring_money | P1 | Base pay and period |
| `pay_frequency` | enum: weekly, fortnightly, semi_monthly, monthly | P2 | Pay cycle |
| `retirement_contribution` | object: rate, included_in_base | P1 | Superannuation / pension / 401(k) |
| `bonus` | object: type, target_amount, target_percent | P1 | Bonus entitlement |
| `commission` | text | P2 | Commission plan |
| `equity` | object: instrument, quantity, vesting_schedule, cliff, acceleration | P1 | Equity grant and vesting |
| `benefits` | strings | P3 | Allowances, vehicle, health cover, etc. |
| `ordinary_hours_per_week` | number | P2 | Standard weekly hours |
| `overtime_terms` | text | P3 | Overtime pay or absorption |
| `leave_entitlements` | list of: leave_type, entitlement | P2 | Annual, personal, parental leave, etc. |
| `industrial_instrument` | string | P2 | Applicable award, CBA or enterprise agreement |
| `notice_period_employer` | duration | P1 | Notice the employer must give |
| `notice_period_employee` | duration | P1 | Notice the employee must give |
| `payment_in_lieu_of_notice` | bool | P2 | Employer may pay instead of notice |
| `garden_leave` | bool | P2 | Employer may direct employee not to work during notice |
| `ip_assignment` | bool | P2 | Work-created IP assigned to employer |
| `moral_rights_consent` | bool | P3 | Consent to acts affecting moral rights |

---

## 6. Contractor

**Identify by:** Independent contractor or consulting agreement with an individual or small business providing personal services, expressly not employment.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### Contractor-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `services_description` | text | P1 | Services to be provided |
| `rate` | recurring_money | P1 | Hourly, daily or fixed rate |
| `fee_cap` | money | P2 | Maximum fees payable |
| `expenses` | object: reimbursable, preapproval_required, cap | P2 | Expense reimbursement |
| `independent_contractor_declaration` | bool | P1 | States no employment relationship (misclassification risk if absent) |
| `control_indicators` | strings | P2 | Terms suggesting employment: set hours, exclusivity, tools supplied |
| `hours_cap` | number | P3 | Max billable hours per period |
| `subcontracting` | enum: prohibited, consent_required, permitted, not_stated | P2 | Right to subcontract or use substitutes |
| `moral_rights_consent` | bool | P3 | Consent to acts affecting moral rights |

---

## 7. Goods Purchase

**Identify by:** Purchase of goods: purchase order, order form or sale-of-goods terms with line items, delivery, and transfer of title and risk.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Goods Purchase-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `line_items` | list of: description, sku, quantity, unit, unit_price | P1 | Goods, quantities, prices |
| `incoterm` | object: rule, version, named_place | P1 | Delivery rule, e.g. FOB Shanghai, Incoterms 2020 |
| `delivery_date` | date | P1 | Required delivery date |
| `delivery_location` | string | P2 | Delivery address |
| `title_transfer` | string | P1 | When ownership passes |
| `risk_transfer` | string | P1 | When risk of loss passes |
| `retention_of_title` | bool | P2 | Seller keeps title until paid |
| `deposit` | money | P2 | Upfront deposit |
| `inspection_period` | duration | P2 | Time to inspect and reject |
| `rejection_remedies` | strings | P2 | Repair, replace, refund |
| `return_rights` | text | P3 | Returns outside warranty |
| `specifications_ref` | string | P2 | Spec the goods must meet |

---

## 8. Supply & Distribution

**Identify by:** Ongoing supply, distribution, reseller or agency arrangement: products, territory, forecasts, minimum orders, rebates.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### Supply & Distribution-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `products` | strings | P1 | Products covered |
| `territory` | jurisdictions | P1 | Where the distributor may sell |
| `channel_role` | enum: distributor, reseller, agent, supplier_only | P2 | Buy-and-resell vs commission agent |
| `price_list_ref` | string | P2 | Applicable price list |
| `volume_rebates` | list of: threshold, rebate | P2 | Tiered rebates |
| `sales_targets` | list of: period, target | P1 | Required sales performance |
| `target_failure_consequence` | enum: termination, loss_of_exclusivity, price_change, none | P1 | Remedy if targets are missed |
| `forecasting` | object: frequency, binding_period | P2 | Forecast obligations |
| `lead_time` | duration | P2 | Order-to-delivery time |
| `minimum_order_quantity` | number | P2 | Per-order minimum |
| `product_recall_obligations` | text | P2 | Recall duties and costs |
| `stock_buyback_on_exit` | bool | P2 | Supplier repurchases stock on termination |
| `sell_off_period` | duration | P2 | Time to sell remaining stock |

---

## 9. Property Lease

**Identify by:** Lease or licence of real property (office, retail or industrial premises): premises, rent, outgoings, make good.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Property Lease-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `premises` | object: address, area, area_unit, car_spaces | P1 | Leased premises |
| `permitted_use` | string | P2 | Permitted use |
| `base_rent` | recurring_money | P1 | Starting rent and period |
| `rent_payment` | object: frequency, in_advance, late_interest | P2 | Payment mechanics |
| `rent_reviews` | list of: review_date, method, value, ratchet | P1 | Scheduled rent changes |
| `outgoings` | object: tenant_pays, tenant_share, annual_estimate | P1 | Tenant share of building costs |
| `security` | object: type, amount | P1 | Security provided (bond, bank guarantee, deposit) |
| `incentives` | object: rent_free_period, fitout_contribution, rent_abatement | P2 | Lease incentives |
| `renewal_options` | list of: term, exercise_window_start, exercise_window_end | P1 | Options to renew and exercise windows |
| `make_good` | object: required, standard | P2 | Restoration at lease end |
| `maintenance_split` | text | P3 | Landlord vs tenant repair duties |
| `relocation_or_demolition_clause` | bool | P2 | Landlord can relocate tenant or end lease to redevelop |

---

## 10. Equipment Lease

**Identify by:** Lease, hire or rental of equipment, vehicles or machinery: lease payments, residual value, purchase option, return conditions.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Equipment Lease-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `equipment` | list of: description, serial_number, quantity | P1 | Leased assets |
| `lease_type` | enum: operating, finance, hire_purchase | P2 | Lease character |
| `lease_payment` | recurring_money | P1 | Periodic payment |
| `security_deposit` | money | P2 | Deposit |
| `residual_value` | money | P2 | Balloon or residual |
| `purchase_option` | object: available, price, exercise_date | P1 | Option to buy at end |
| `usage_limits` | string | P2 | Hours/mileage limits and excess charges |
| `maintenance_responsibility` | enum: lessor, lessee, shared | P2 | Who maintains |
| `return_conditions` | text | P2 | Condition and logistics on return |
| `early_termination_payout` | text | P1 | Amount payable on early exit |

---

## 11. Loan

**Identify by:** Loan, credit or facility agreement: facility limit, interest, repayment, security, financial covenants, events of default.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Loan-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `facility_type` | enum: term_loan, revolving, overdraft, bridge, other | P1 | Facility type |
| `facility_limit` | money | P1 | Principal or commitment |
| `availability_period` | duration | P2 | Window to draw funds |
| `interest` | object: rate_type, fixed_rate, base_rate, margin, interest_period | P1 | e.g. SOFR or BBSW + margin |
| `default_interest_margin` | percent | P2 | Extra interest on overdue amounts |
| `fees` | list of: fee_type, amount, rate | P1 | Facility fees |
| `repayment` | object: profile, schedule | P1 | Repayment profile and dates |
| `prepayment` | object: permitted, notice_period, fee | P2 | Early repayment terms |
| `financial_covenants` | list of: metric, threshold, test_frequency | P1 | e.g. LVR, ICR, leverage |
| `security_collateral` | strings | P1 | Assets securing the loan |
| `guarantor_refs` | party_refs | P1 | Guarantor party ids |
| `events_of_default` | strings | P1 | Default triggers |
| `cross_default_threshold` | money | P2 | Other-debt amount that triggers default |
| `negative_pledge` | bool | P2 | Borrower may not grant security to others |
| `reporting_obligations` | strings | P2 | Financials, compliance certificates |
| `purpose` | text | P3 | Permitted use of funds |

---

## 12. IP License

**Identify by:** Licence of patents, trade marks, copyright, software or technology for fees or royalties (not a hosted SaaS subscription).

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### IP License-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `licensed_ip` | list of: ip_type, identifier, jurisdiction | P1 | Registration numbers or descriptions |
| `upfront_fee` | money | P1 | Initial licence fee |
| `royalty` | object: rate, base, per_unit_amount, reporting_frequency, payment_due | P1 | Royalty terms |
| `minimum_annual_royalty` | money | P1 | Guaranteed minimum |
| `milestone_payments` | list of: event, amount | P1 | Event-based payments |
| `improvements_ownership` | enum: licensor, licensee, joint, creator, not_stated | P2 | Who owns improvements |
| `grant_back` | bool | P2 | Licensee must license improvements back |
| `enforcement_rights` | enum: licensor_only, licensee_first, licensee_with_consent, not_stated | P2 | Who can sue infringers |
| `no_challenge_clause` | bool | P2 | Licensee may not challenge validity |
| `quality_control` | text | P3 | Trademark quality standards |
| `post_termination_sell_off` | duration | P2 | Time to sell licensed stock after exit |

---

## 13. JV & Partnership

**Identify by:** Joint venture, partnership, shareholders' or strategic alliance agreement: contributions, ownership, governance, profit sharing, exit.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### JV & Partnership-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `jv_structure` | enum: incorporated, unincorporated, partnership, llp | P2 | Legal form |
| `jv_entity_name` | string | P2 | JV vehicle name |
| `ownership` | list of: party_ref, percentage | P1 | Ownership split |
| `capital_contributions` | list of: party_ref, amount, form, due_date | P1 | Initial contributions |
| `additional_funding` | object: mandatory, cap, dilution_on_default | P1 | Further funding obligations |
| `profit_loss_split` | list of: party_ref, percentage | P1 | Economic split if different from ownership |
| `distribution_policy` | text | P2 | When profits are paid out |
| `board_composition` | list of: party_ref, seats | P2 | Board appointment rights |
| `reserved_matters` | strings | P1 | Decisions needing unanimity or supermajority |
| `voting_thresholds` | text | P2 | Ordinary vs special decisions |
| `deadlock_mechanism` | enum: escalation, mediation, arbitration, shotgun, texas_shootout, put_call, dissolution, none | P2 | How deadlocks are broken |
| `transfer_restrictions` | text | P1 | Lock-ups and consent to transfer |
| `tag_along` | object: exists, threshold | P2 | Minority can join a sale |
| `drag_along` | object: exists, threshold | P2 | Majority can force a sale |
| `put_call_options` | text | P2 | Option rights to buy or sell interests |
| `default_events_and_remedies` | text | P1 | Consequences when a partner defaults |
| `dissolution_triggers` | strings | P2 | Events ending the JV |

---

## 14. Share-Asset Purchase

**Identify by:** Sale and purchase of shares or of a business or its assets: purchase price, conditions precedent, completion, warranties, indemnities.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### Share-Asset Purchase-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `transaction_type` | enum: share_purchase, asset_purchase, merger | P1 | Deal structure |
| `target` | string | P1 | Company or business acquired |
| `purchase_price` | money | P1 | Headline price |
| `consideration` | list of: form, amount | P1 | Form of consideration |
| `price_mechanism` | enum: completion_accounts, locked_box, fixed | P1 | Price adjustment approach |
| `locked_box_date` | date | P2 | Locked box accounts date |
| `working_capital_target` | money | P2 | Target for completion adjustment |
| `earn_out` | object: maximum, metric, period | P1 | Contingent consideration |
| `escrow_holdback` | object: amount, release_period | P1 | Amount withheld for claims |
| `deferred_consideration` | list of: amount, due_date | P1 | Later payments |
| `conditions_precedent` | strings | P1 | Regulatory, shareholder, financing conditions |
| `long_stop_date` | date | P1 | Deadline to satisfy conditions |
| `completion_date` | relative_date | P1 | Closing date |
| `material_adverse_change` | bool | P2 | Buyer walk-away right on MAC |
| `warranty_claim_periods` | object: general, tax, fundamental | P1 | Time limits for claims |
| `claim_thresholds` | object: de_minimis, basket, basket_type | P2 | Minimum claim sizes |
| `seller_liability_cap` | object: amount, percent_of_price | P1 | Cap on warranty claims |
| `specific_indemnities` | strings | P1 | Indemnities for known risks |
| `wi_insurance` | object: exists, limit, retention | P2 | Warranty & indemnity insurance |

---

## 15. Franchise

**Identify by:** Franchise agreement granting the right to run a business under the franchisor's brand and system: franchise fees, royalties, territory.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Commercial

| Field | Type | Priority | Description |
|---|---|---|---|
| `total_contract_value` | money | P1 | Stated or computable total value |
| `payment_terms` | object: due_period, due_trigger, invoicing_frequency, currency | P1 | When and how payment is due |
| `late_payment_interest` | object: rate, basis | P2 | Interest or fees on overdue amounts |
| `price_escalation` | object: mechanism, rate, cap, frequency, notice_period | P1 | How prices can increase over the term |
| `minimum_commitment` | object: amount, quantity, unit, period, shortfall_remedy | P1 | Minimum spend or volume a party must buy |
| `volume_restriction` | text | P2 | Usage/purchase caps beyond which fees or consent apply |
| `most_favored_nation` | bool | P2 | Entitlement to terms as good as any other customer |
| `price_restrictions` | text | P2 | Limits on raising or lowering prices |
| `revenue_profit_sharing` | text | P2 | Obligation to share revenue or profit |
| `tax_treatment` | enum: exclusive, inclusive, not_stated | P3 | Whether prices include GST/VAT/sales tax |
| `audit_rights` | object: exists, frequency, notice_period, cost_bearer | P2 | Right to audit records or compliance |
| `post_termination_services` | object: required, period, chargeable | P2 | Transition or wind-down services after exit |

### Restrictive Covenants

| Field | Type | Priority | Description |
|---|---|---|---|
| `exclusivity` | object: exists, beneficiary, scope, territory, duration | P1 | Exclusive dealing obligations |
| `non_compete` | restriction | P1 | Restriction on competing |
| `competitive_restriction_exception` | text | P2 | Carve-outs from non-compete or exclusivity |
| `non_solicit_customers` | restriction | P2 | Ban on soliciting the other party's customers |
| `non_solicit_employees` | restriction | P2 | Ban on soliciting or hiring the other party's staff |
| `non_disparagement` | bool | P3 | Obligation not to disparage |
| `first_rights` | object: type, subject, exercise_period | P2 | Right of first refusal / offer / negotiation |

### IP & Data

| Field | Type | Priority | Description |
|---|---|---|---|
| `ip_ownership` | object: ownership_model, owner_party_ref, background_ip_retained | P1 | Who owns IP created under the contract |
| `license_grant` | object: licensed_subject, licensee_ref, exclusivity, territory, field_of_use, transferable, sublicensable, perpetual, irrevocable, licensor_affiliates_included, licensee_affiliates_included, unlimited_usage | P1 | Scope of any licence granted |
| `source_code_escrow` | object: exists, release_triggers, escrow_agent | P2 | Source code released on triggers |
| `covenant_not_to_sue` | text | P3 | Promise not to sue or challenge IP |
| `data_protection` | object: personal_data_processed, supplier_role, dpa_ref, breach_notification_period | P2 | Personal data handling (detailed in the DPA type) |
| `publicity` | enum: prohibited, consent_required, permitted, not_stated | P3 | Right to use the other party's name/logo |

### Franchise-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `franchise_territory` | object: description, jurisdictions, exclusive | P1 | Franchise territory |
| `outlet_location` | string | P2 | Site address |
| `initial_franchise_fee` | money | P1 | Upfront fee |
| `franchise_royalty` | object: rate, base, minimum | P1 | Ongoing royalty |
| `marketing_levy` | object: rate, base | P1 | Marketing fund contribution |
| `other_fees` | list of: name, amount | P2 | Technology, training, renewal, transfer fees |
| `estimated_establishment_cost` | money | P2 | Fit-out and setup estimate |
| `disclosure_document_date` | date | P2 | Pre-contract disclosure document date |
| `cooling_off_period` | duration | P2 | Statutory or contractual cooling-off |
| `performance_minimums` | text | P1 | Required sales or KPIs |
| `approved_suppliers_mandatory` | bool | P2 | Must buy from nominated suppliers |
| `refurbishment_obligations` | text | P2 | Required periodic upgrades |
| `transfer_conditions` | text | P2 | Conditions to sell the franchise |
| `de_identification_obligations` | text | P3 | Removing branding after exit |

---

## 16. Construction

**Identify by:** Construction, building or engineering works contract: contract sum, progress claims, practical completion, defects liability, variations.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Risk & Liability

| Field | Type | Priority | Description |
|---|---|---|---|
| `liability_cap` | object: cap_type, amount, fees_multiple, lookback_period, applies_to, party_refs | P1 | Maximum aggregate liability |
| `uncapped_liabilities` | strings | P1 | Liabilities carved out of the cap (fraud, IP, data breach) |
| `consequential_loss_excluded` | bool | P2 | Indirect/consequential damages excluded |
| `indemnities` | list of: indemnifying_party, indemnified_party, triggers, subject_to_cap | P1 | Who indemnifies whom, for what |
| `warranties` | strings | P2 | Key warranties given |
| `warranty_duration` | duration | P2 | How long warranties last |
| `liquidated_damages` | object: trigger, rate, cap | P1 | Pre-agreed damages, e.g. for delay |
| `insurance_requirements` | list of: policy_type, minimum_cover, obligated_party | P2 | Required policies and limits |
| `force_majeure` | object: exists, termination_after, excludes_payment_obligations | P3 | Relief for events beyond control |
| `compliance_obligations` | strings | P3 | Anti-bribery, sanctions, modern slavery, code of conduct |

### Construction-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `site_address` | string | P2 | Site |
| `contract_form` | string | P2 | Standard form, e.g. AS 4000, FIDIC Red Book, JCT, AIA A201 |
| `contract_sum` | money | P1 | Contract price |
| `pricing_basis` | enum: lump_sum, schedule_of_rates, cost_plus, guaranteed_maximum_price | P1 | Pricing basis |
| `progress_claims` | object: frequency, payment_period | P1 | Claim cycle and payment time |
| `retention` | object: percent, cap, release_trigger | P1 | Retention money |
| `security` | object: type, amount | P1 | Security provided (bond, bank guarantee, deposit) |
| `date_for_practical_completion` | date | P1 | Completion deadline |
| `extension_of_time_grounds` | strings | P2 | Qualifying causes of delay |
| `defects_liability_period` | duration | P1 | Defects period |
| `variations_procedure` | text | P2 | How variations are directed and valued |
| `latent_conditions_risk` | enum: principal, contractor, shared, not_stated | P2 | Who bears ground/site risk |
| `time_bar_notice_period` | duration | P1 | Deadline to notify claims or lose them |
| `superintendent` | string | P3 | Contract administrator |

---

## 17. DPA

**Identify by:** Data processing agreement or addendum setting how a processor handles personal data on behalf of a controller.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### DPA-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `processing_purpose` | text | P1 | Why data is processed |
| `data_categories` | strings | P1 | Types of personal data |
| `data_subject_categories` | strings | P2 | Whose data |
| `special_category_data` | bool | P1 | Health, biometric, etc. |
| `processing_duration` | duration | P2 | How long processing lasts |
| `subprocessor_authorization` | enum: general, specific | P2 | Authorisation model |
| `subprocessor_objection_period` | duration | P3 | Time to object to new subprocessors |
| `breach_notification_period` | duration | P1 | e.g. PT72H |
| `international_transfers` | object: occurs, mechanism, destinations | P1 | Cross-border transfers and safeguards |
| `security_measures_ref` | string | P3 | Technical/organisational measures annex |
| `dpa_audit_rights` | text | P2 | Controller audit rights |
| `deletion_or_return` | object: choice, period | P2 | End-of-processing obligation |
| `liability_reference` | text | P3 | Whether main-agreement caps apply |

---

## 18. Amendment

**Identify by:** Amendment, variation, addendum or change order that modifies an existing agreement rather than standing alone.

### Core

| Field | Type | Priority | Description |
|---|---|---|---|
| `title` | string | P3 | Document title as written |
| `document_status` | enum: draft, executed, expired, terminated, superseded | P1 | Lifecycle status from signatures and dates |
| `language` | language | P3 | ISO 639-1 language code |
| `parent_agreement_ref` | string | P2 | Master/original agreement this document attaches to or amends |
| `order_of_precedence` | strings | P3 | Which document prevails when terms conflict |
| `parties` | list of: id, name, role, entity_type, registration_number, incorporation_jurisdiction, address, notice_email | P1 | All contracting parties and their roles |
| `signatories` | list of: name, title, party_ref, signed_date | P2 | Who signed, in what capacity, and when |
| `execution_date` | date | P1 | Date the last party signed |
| `effective_date` | relative_date | P1 | Date obligations start; may be relative to an event |
| `expiration_date` | relative_date | P1 | End of term; computed when stated as a duration |
| `initial_term` | duration | P1 | Length of the initial term |
| `renewal` | object: auto_renewal, renewal_term, non_renewal_notice_period, max_renewals, renewal_price_change | P1 | Renewal mechanics and opt-out notice |
| `termination_for_convenience` | object: available_to, party_refs, notice_period, termination_fee | P1 | Right to exit without cause |
| `termination_for_cause` | object: triggers, cure_period, insolvency_trigger | P1 | Breach-based termination grounds and cure period |
| `change_of_control` | object: triggers_termination, requires_consent, requires_notice | P2 | Consequences of a party being acquired |
| `anti_assignment` | object: restricted, consent_required, consent_not_unreasonably_withheld, exceptions | P2 | Limits on transferring the contract |
| `confidentiality` | object: exists, duration, survives_termination | P2 | General confidentiality obligation (detailed in the NDA type) |
| `governing_law` | jurisdiction | P2 | ISO 3166 code, e.g. AU-NSW, US-NY, GB |
| `dispute_resolution` | object: method, venue, arbitral_rules, seat, escalation_steps | P2 | Forum and method for resolving disputes |
| `notice_requirements` | object: methods, addresses | P3 | How formal notices must be served |
| `third_party_beneficiary` | bool | P3 | Non-parties can enforce terms |
| `survival_clauses` | strings | P3 | Clauses that survive termination |

### Amendment-Specific

| Field | Type | Priority | Description |
|---|---|---|---|
| `amendment_number` | int | P3 | Sequence number |
| `changes` | list of: clause_ref, change_type, new_text, affected_field | P1 | Each change mapped to the schema field it overrides, e.g. core.expiration_date |
| `extends_term` | bool | P1 | Amendment changes the term |
| `changes_price` | bool | P1 | Amendment changes pricing |

---

## 19. Other

**Identify by:** Fallback for contracts that match none of the types above.

**Includes:** Core, Commercial, Risk & Liability
