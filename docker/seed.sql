-- Default configuration for ContractExtraction. Applied after schema.sql on an empty database.
-- Values come from the prototype (DocumentExtraction): search configs, contract field templates, system prompts.
-- Generated once; edit freely. Rows are looked up by their natural keys, so ids stay random.

BEGIN;

-- Providers. OpenRouter is disabled until OPENROUTER_API_KEY is set and the provider is enabled.
INSERT INTO llm_providers (key, kind, base_url, api_key_env, is_enabled) VALUES
    ('ollama-local', 'ollama',     'http://localhost:11434',       NULL,                 true),
    ('openrouter',   'openrouter', 'https://openrouter.ai/api/v1', 'OPENROUTER_API_KEY', false);

-- Models
INSERT INTO llm_models (provider_id, name, kind, context_window, embedding_dimension)
SELECT p.id, m.name, m.kind, m.context_window, m.embedding_dimension
FROM llm_providers p
JOIN (VALUES
    ('nomic-embed-text:latest', 'embedding', 8192, 768),
    ('llama3.1:8b',             'chat',      131072, NULL::integer)
) AS m (name, kind, context_window, embedding_dimension) ON true
WHERE p.key = 'ollama-local';

-- Model profiles (generation settings)
INSERT INTO model_profiles (name, description, model_id, temperature, top_p, top_k, num_ctx, json_mode, timeout_seconds)
SELECT v.name, v.description, m.id, v.temperature, v.top_p, v.top_k, 8192, true, 600
FROM (VALUES
    ('extraction-default', 'Field extraction with llama3.1:8b', 0.2, 0.2, 20),
    ('judge-default',      'LLM judge with llama3.1:8b',        0.8, 0.8, 100)
) AS v (name, description, temperature, top_p, top_k)
JOIN llm_models m ON m.name = 'llama3.1:8b' AND m.kind = 'chat';

-- System prompts
INSERT INTO prompt_templates (name, version, role, body) VALUES
    ('extraction_system', 1, 'extraction_system', 'You are a precise information extraction assistant.
Always follow these rules:
1. Only extract values exactly as they appear in the text.
2. If a field is not present, leave it as an empty string.
3. Return output strictly in JSON format with no extra commentary.
4. Always follow the JSON schema provided by the user prompt.'),
    ('judge_system',      1, 'judge_system',      'You are evaluating correctness of the terms.
Evaluate strictly based on QUESTION and CONTEXT.

Return JSON only:
{
  "status": "PASS" | "FAIL",
  "issue": "NONE" | "HALLUCINATION" | "INCOMPLETE" | "NO_CONTEXT",
  "explanation": "<brief reason for the decision>"
}

Evaluation Criteria:
- PASS: The answer is fully supported by the context and complete with respect to the question.
- FAIL: The answer contains any unsupported claim, fabricated value, missing required information, or the context does not contain relevant information needed to answer the question.

Issue Definitions:
- NONE → Used only when status is PASS.
- HALLUCINATION → The answer includes information not supported by the context, contradicts the context, or incorrectly states something is missing when it exists.
- INCOMPLETE → The answer is partially correct but omits required information that is present in the context.
- NO_CONTEXT → The provided context is irrelevant or does not contain information required to answer the question.

Rules:
- If any part of the answer is not grounded in the context → FAIL with HALLUCINATION.
- If required information exists in the context but is missing in the answer → FAIL with INCOMPLETE.
- If the answer states information is not available but it exists in the context → FAIL with HALLUCINATION.
- If the context does not contain sufficient or relevant information → FAIL with NO_CONTEXT.
- Be strict. Do not assume correctness.
- The explanation must be concise (1–2 sentences).
- Output JSON only.');

-- Decomposition and indexing
INSERT INTO decomposition_configs (name, description, method, text_format)
VALUES
    ('default', 'pymupdf4llm Markdown, invisible OCR text kept, repeating headers/footers removed', 'pymupdf', 'md'),
    ('ocr',     'Tesseract OCR of rendered pages (scanned PDFs without a text layer), Markdown',       'ocr',     'md'),
    ('hybrid',  'pymupdf text where available, OCR for image regions, Markdown',                     'hybrid',  'md');

INSERT INTO index_configs (name, description, embedding_model_id, chunk_size, chunk_overlap, vector_store, distance)
SELECT 'default', '2000-char chunks with 300 overlap, nomic-embed-text, Qdrant', id, 2000, 300, 'qdrant', 'cosine'
FROM llm_models WHERE name = 'nomic-embed-text:latest' AND kind = 'embedding';

-- RAG retrieval configurations
INSERT INTO retrieval_configs (name, description, top_k, score_threshold, query_expansion) VALUES
    ('RAG01', 'top 10, threshold 0.5, with query expansion', 10, 0.5, true),
    ('RAG02', 'top 5, threshold 0.5, with query expansion', 5, 0.5, true),
    ('RAG03', 'top 3, threshold 0.5, with query expansion', 3, 0.5, true),
    ('RAG04', 'top 10, threshold 0.7, without query expansion', 10, 0.7, false),
    ('RAG05', 'top 5, threshold 0.7, without query expansion', 5, 0.7, false),
    ('RAG06', 'top 3, threshold 0.7, without query expansion', 3, 0.7, false),
    ('RAG07', 'top 10, threshold 0.5, with query expansion', 10, 0.5, true);

-- Contract fields
INSERT INTO field_sets (name, version, description)
VALUES ('contract_fields', 1, 'Commercial contract data points (prototype field templates)');

-- 1. Customer Name
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'customer_name', 'Customer Name', 'The full legal name of the entity or individual identified in the contract as the “Customer”, “Client”, “Buyer”, “Purchaser”, “Subscriber”, or any equivalent term referring to the party receiving goods or services.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
customer_name

Definition of customer_name:
The full legal name of the entity or individual identified in the contract as the “Customer”, “Client”, “Buyer”, “Purchaser”, “Subscriber”, or any equivalent term referring to the party receiving goods or services.
This is typically found in:
The agreement preamble (e.g., “This Agreement is made between … and …”)
The “Parties” section
The Definitions section where “Customer” is defined
The contract header or metadata
The signature block
Extraction Rules:
Extract the full legal name exactly as written in the text.
Include any suffixes such as Pty Ltd, LLC, Inc., Ltd, Corporation, etc., if present.
Do not infer, reformat, abbreviate, or correct the name.
Do not extract the service provider name.
If multiple parties exist, extract only the one defined as the Customer (or equivalent).
If not explicitly identifiable, return an empty string.
JSON Format:
{
"customer_name": ""
}',
       1
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Customer name in the agreement'),
    (2, 'Legal name of the customer entity'),
    (3, 'Client name specified in the contract'),
    (4, 'Name of the contracting customer'),
    (5, 'Party defined as Customer in this agreement'),
    (6, 'Registered name of the client company'),
    (7, 'Agreement made between company and customer'),
    (8, 'Entered into by and between provider and customer'),
    (9, 'Full legal name of the service recipient'),
    (10, 'Entity identified as the customer in this contract'),
    (11, 'Customer details section showing legal name'),
    (12, 'Contract header listing customer name'),
    (13, 'Parties to this agreement including customer name'),
    (14, 'Purchaser name mentioned in the agreement'),
    (15, 'Subscriber legal name in the contract'),
    (16, 'Licensee name defined in this agreement'),
    (17, 'Buyer name specified in contract terms'),
    (18, 'Company referred to as Customer in definitions section'),
    (19, 'The party designated as Client in this contract'),
    (20, 'Corporate name of the contracting party receiving services'),
    (21, 'Customer information section with entity name'),
    (22, 'First party or second party identified as customer'),
    (23, 'Name of the organization entering this agreement as customer'),
    (24, 'Legal entity name defined as Customer'),
    (25, 'Contract metadata showing customer identity'),
    (26, 'Customer signature block with entity name'),
    (27, 'Client company name in agreement preamble'),
    (28, 'Organization identified as the customer in this document'),
    (29, 'Entity entering into this agreement as the customer'),
    (30, 'Official name of the customer as stated in the contract')
) AS v (position, query) ON true
WHERE f.key = 'customer_name';

-- 2. End Customer Name
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'end_customer_name', 'End Customer Name', 'The full legal name of the entity or individual that is the ultimate recipient of the goods or services in the contract, often referred to as the “End Customer”, “Final Customer”, “Ultimate Customer”, or equivalent.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
end_customer_name

Definition of end_customer_name:
The full legal name of the entity or individual that is the ultimate recipient of the goods or services in the contract, often referred to as the “End Customer”, “Final Customer”, “Ultimate Customer”, or equivalent.
This is typically found in:
The agreement preamble (e.g., “This Agreement is made between … and … for the benefit of …”)
The “Parties” or “Definitions” section where the End Customer is identified
Statements of Work, schedules, or annexes specifying the customer
The signature block if present

Extraction Rules:
Extract the full legal name exactly as written in the text.
Include suffixes such as Pty Ltd, LLC, Inc., Ltd, Corporation, etc., if present.
Do not infer, reformat, abbreviate, or correct the name.
Do not extract the reseller or service provider name.
If multiple end customers exist, extract only the one explicitly defined as End Customer.
If not explicitly identifiable, return an empty string.

JSON Format:
{
"end_customer_name": ""
}

Input Chunks:',
       2
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'End customer name in the agreement'),
    (2, 'Legal name of the end customer'),
    (3, 'Entity identified as End Customer in this contract'),
    (4, 'Party defined as End Customer in the definitions section'),
    (5, 'Full legal name of the end client'),
    (6, 'Ultimate customer name mentioned in the contract'),
    (7, 'Name of the end user organization'),
    (8, 'Company designated as End Customer'),
    (9, 'End Customer details section with legal name'),
    (10, 'Agreement referencing the End Customer entity'),
    (11, 'Contract made for the benefit of the End Customer'),
    (12, 'End Customer identified in the parties clause'),
    (13, 'Registered name of the End Customer company'),
    (14, 'Organization referred to as the End Customer'),
    (15, 'End Customer information in contract metadata'),
    (16, 'Service delivered to End Customer named in agreement'),
    (17, 'Name of the ultimate purchaser (End Customer)'),
    (18, 'Entity receiving services as End Customer'),
    (19, 'End Customer defined term and corresponding name'),
    (20, 'Agreement between supplier and End Customer'),
    (21, 'Third-party End Customer name in this contract'),
    (22, 'End Customer listed in statement of work'),
    (23, 'End Customer specified in schedule or annex'),
    (24, 'Corporate name of the End Customer organization'),
    (25, 'Client of the reseller identified as End Customer'),
    (26, 'End Customer mentioned in order form'),
    (27, 'Name of the final customer receiving deliverables'),
    (28, 'End Customer signature block with entity name'),
    (29, 'End Customer referenced in master service agreement'),
    (30, 'Official name of the End Customer as stated in contract')
) AS v (position, query) ON true
WHERE f.key = 'end_customer_name';

-- 3. Customer Contract Number
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'customer_contract_number', 'Customer Contract Number', 'The unique identifier assigned to the agreement with the customer. This may be called “Contract Number”, “Agreement ID”, “Client Contract ID”, or similar, and is often used for billing, reference, or legal identification of the contract.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
customer_contract_number

Definition of customer_contract_number:
The unique identifier assigned to the agreement with the customer. This may be called “Contract Number”, “Agreement ID”, “Client Contract ID”, or similar, and is often used for billing, reference, or legal identification of the contract.
This is typically found in:
The agreement header or preamble
Contract metadata or document references
The “Definitions” section where contract numbers are mentioned
Annexes, schedules, or signature blocks
Extraction Rules:
Extract the contract number exactly as it appears in the text.
Include any letters, numbers, dashes, slashes, or special symbols.
Do not infer, reformat, or abbreviate.
Do not extract unrelated numbers (e.g., page numbers, invoice numbers).
If the contract number is not explicitly present, return an empty string.
JSON Format:
{
"customer_contract_number": ""
}

Input Chunks:',
       3
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Customer contract number in the agreement'),
    (2, 'Contract ID assigned to the customer'),
    (3, 'Unique identifier of the customer agreement'),
    (4, 'Customer agreement reference number'),
    (5, 'Legal contract number for the customer'),
    (6, 'Client contract ID in the document'),
    (7, 'Agreement reference or contract ID'),
    (8, 'Contract identifier associated with the customer'),
    (9, 'Registered contract number of the customer'),
    (10, 'Contract number mentioned in the parties clause'),
    (11, 'Customer order or contract reference'),
    (12, 'Official contract ID in the agreement'),
    (13, 'Customer contract metadata including number'),
    (14, 'Documented contract number for the client'),
    (15, 'Agreement ID listed in the header'),
    (16, 'Contract reference stated in definitions'),
    (17, 'Customer contract number in signature block'),
    (18, 'Unique contract identifier of the client'),
    (19, 'Customer agreement number in annex or schedule'),
    (20, 'Contract reference code assigned to customer'),
    (21, 'Agreement ID or customer contract number'),
    (22, 'Customer purchase agreement number'),
    (23, 'Contract number for the purchasing party'),
    (24, 'Customer contract number in preamble'),
    (25, 'Legal reference number for the customer contract'),
    (26, 'Client agreement identifier'),
    (27, 'Contract ID used for billing or invoicing'),
    (28, 'Reference number for the customer contract'),
    (29, 'Agreement identifier of the contracting customer'),
    (30, 'Customer contract or order number')
) AS v (position, query) ON true
WHERE f.key = 'customer_contract_number';

-- 4. Payment Terms
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'payment_terms', 'Payment Terms', 'The specific conditions under which the customer must make payments as defined in the contract. This may include payment schedules, due dates, billing cycles, milestones, currency, late fees, or other terms governing the transfer of funds.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
payment_terms

Definition of payment_terms:
The specific conditions under which the customer must make payments as defined in the contract. This may include payment schedules, due dates, billing cycles, milestones, currency, late fees, or other terms governing the transfer of funds.
This is typically found in:
Payment clauses or sections of the agreement
Billing or invoicing schedules
Annexes, Schedules, or Statements of Work
Sections specifying financial obligations or settlement terms
Extraction Rules:
Extract the payment terms exactly as written in the contract text.
Include numbers, percentages, dates, and descriptions exactly as they appear.
Do not infer, summarize, or reformat the terms.
If payment terms are not explicitly present, return an empty string.
JSON Format:
{
"payment_terms": []
}
Input Chunks::',
       4
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Payment terms in the agreement'),
    (2, 'Customer payment conditions'),
    (3, 'Payment schedule specified in the contract'),
    (4, 'Invoice and payment terms for the customer'),
    (5, 'Contractual payment obligations'),
    (6, 'Terms of payment for goods or services'),
    (7, 'Payment due dates outlined in the agreement'),
    (8, 'Billing and payment instructions'),
    (9, 'Customer payment responsibilities'),
    (10, 'Payment milestones or installment terms'),
    (11, 'Pricing and payment clauses'),
    (12, 'Financial terms in the contract'),
    (13, 'Payment obligations of the client'),
    (14, 'Contract section describing payment methods'),
    (15, 'Payment plan or schedule for customer'),
    (16, 'Terms of invoice payment'),
    (17, 'Payment instructions and deadlines'),
    (18, 'Customer payment timing and conditions'),
    (19, 'Contract-defined payment periods'),
    (20, 'Payment terms including penalties or discounts'),
    (21, 'Billing frequency and payment terms'),
    (22, 'Deposit, advance, or prepayment terms'),
    (23, 'Final payment and settlement clauses'),
    (24, 'Payment obligations in signature or annex'),
    (25, 'Contracted fees and payment details'),
    (26, 'Payment triggers or conditions for delivery'),
    (27, 'Terms covering payment adjustments or credits'),
    (28, 'Customer financial obligations under the contract'),
    (29, 'Payment clauses including late fees'),
    (30, 'Payment-related sections of the agreement')
) AS v (position, query) ON true
WHERE f.key = 'payment_terms';

-- 5. Project Name
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'project_name', 'Project Name', 'The official name or title of the project covered by the contract. This may be explicitly stated in the preamble, definitions, scope of work, schedules, annexes, or metadata sections. It identifies the initiative, engagement, or work being executed under the agreement.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
project_name

Definition of project_name:
The official name or title of the project covered by the contract. This may be explicitly stated in the preamble, definitions, scope of work, schedules, annexes, or metadata sections. It identifies the initiative, engagement, or work being executed under the agreement.
Extraction Rules:
Extract the project name exactly as written in the text.
Include all parts of the name, including abbreviations, codes, or suffixes if present.
Do not infer, reformat, or abbreviate.
If the project name is not explicitly present, return an empty string.
JSON Format:
{
"project_name": ""
}
Input Chunks:',
       5
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Project name mentioned in the agreement'),
    (2, 'Official title of the project'),
    (3, 'Name of the project being executed under the contract'),
    (4, 'Contract section specifying project name'),
    (5, 'Project identifier or designation in the document'),
    (6, 'Title of the project listed in the agreement'),
    (7, 'Project reference name for the contract'),
    (8, 'Contractual project name or title'),
    (9, 'Name of the initiative or engagement'),
    (10, 'Project description header with name'),
    (11, 'Agreement section detailing project name'),
    (12, 'Project label or code mentioned in contract'),
    (13, 'Full project name as stated in agreement'),
    (14, 'Project referenced in scope of work'),
    (15, 'Contract section on project identification'),
    (16, 'Project title in preamble or introduction'),
    (17, 'Official name of the contracted project'),
    (18, 'Project referred to in schedules or annexes'),
    (19, 'Project title or identifier in definitions'),
    (20, 'Agreement specifying the project name'),
    (21, 'Project designation in statement of work'),
    (22, 'Name of the engagement under this contract'),
    (23, 'Project title used in billing or documentation'),
    (24, 'Project name listed in header or metadata'),
    (25, 'Full legal name of the project'),
    (26, 'Project reference used in deliverables'),
    (27, 'Project name mentioned in scope clause'),
    (28, 'Project title for client or customer agreement'),
    (29, 'Contractual name of the project'),
    (30, 'Project identifier or reference code')
) AS v (position, query) ON true
WHERE f.key = 'project_name';

-- 6. Planned Project Start Date
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'planned_project_start_date', 'Planned Project Start Date', 'The specific date on which the project covered by the contract is scheduled to begin. This may appear in the preamble, project schedule, statement of work, scope of work, or contract metadata sections.', 'date',
       'Task: From the given contract text chunks, extract the following fields:
planned_project_start_date

Definition of planned_project_start_date:
The specific date on which the project covered by the contract is scheduled to begin. This may appear in the preamble, project schedule, statement of work, scope of work, or contract metadata sections.
Extraction Rules:
Extract the date exactly as written in the text.
Include full format as present (e.g., DD/MM/YYYY, Month DD, YYYY).
Do not infer, convert, or standardize the date.
If the planned project start date is not explicitly present, return an empty string.
JSON Format:
{
"planned_project_start_date": ""
}
Input Chunks:',
       6
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Planned project start date in the agreement'),
    (2, 'Scheduled commencement date of the project'),
    (3, 'Official project start date mentioned in contract'),
    (4, 'Contract section specifying project initiation date'),
    (5, 'Project kickoff date in the agreement'),
    (6, 'Date on which the project is planned to begin'),
    (7, 'Commencement date of the contracted project'),
    (8, 'Start date listed in the project schedule'),
    (9, 'Planned initiation date for project execution'),
    (10, 'Project start timeline mentioned in contract'),
    (11, 'Contracted start date for project activities'),
    (12, 'Project start date as per statement of work'),
    (13, 'Scheduled date for project launch'),
    (14, 'Project commencement timeline in agreement'),
    (15, 'Contractual start date of the project'),
    (16, 'Start date indicated in scope of work'),
    (17, 'Planned date for beginning project deliverables'),
    (18, 'Project kickoff schedule mentioned in agreement'),
    (19, 'Date when project activities are to start'),
    (20, 'Agreed project start date in contract clauses'),
    (21, 'Initiation date of the project engagement'),
    (22, 'Project start date referenced in schedules or annexes'),
    (23, 'Contracted commencement date'),
    (24, 'Timeline indicating project start'),
    (25, 'Planned date of project execution'),
    (26, 'Project launch date in agreement documentation'),
    (27, 'Project start date in header or metadata'),
    (28, 'Project scheduled start as per agreement'),
    (29, 'Project commencement date mentioned in contract'),
    (30, 'Start date of the engagement under this contract')
) AS v (position, query) ON true
WHERE f.key = 'planned_project_start_date';

-- 7. Planned Project End Date
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'planned_project_end_date', 'Planned Project End Date', 'The specific date on which the project covered by the contract is scheduled to finish or be completed. This may appear in the preamble, project schedule, statement of work, scope of work, or contract metadata sections.', 'date',
       'Task: From the given contract text chunks, extract the following fields:
planned_project_end_date

Definition of planned_project_end_date:
The specific date on which the project covered by the contract is scheduled to finish or be completed. This may appear in the preamble, project schedule, statement of work, scope of work, or contract metadata sections.
Extraction Rules:
Extract the date exactly as written in the text.
Include full format as present (e.g., DD/MM/YYYY, Month DD, YYYY).
Do not infer, convert, or standardize the date.
If the planned project end date is not explicitly present, return an empty string.
JSON Format:
{
"planned_project_end_date": ""
}
Input Chunks:',
       7
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Planned project end date in the agreement'),
    (2, 'Scheduled completion date of the project'),
    (3, 'Official project end date mentioned in contract'),
    (4, 'Contract section specifying project closure date'),
    (5, 'Project finish date in the agreement'),
    (6, 'Date on which the project is planned to end'),
    (7, 'Completion date of the contracted project'),
    (8, 'End date listed in the project schedule'),
    (9, 'Planned conclusion date for project execution'),
    (10, 'Project end timeline mentioned in contract'),
    (11, 'Contracted end date for project activities'),
    (12, 'Project finish date as per statement of work'),
    (13, 'Scheduled date for project completion'),
    (14, 'Project closure timeline in agreement'),
    (15, 'Contractual end date of the project'),
    (16, 'End date indicated in scope of work'),
    (17, 'Planned date for finishing project deliverables'),
    (18, 'Project completion schedule mentioned in agreement'),
    (19, 'Date when project activities are to conclude'),
    (20, 'Agreed project end date in contract clauses'),
    (21, 'Termination date of the project engagement'),
    (22, 'Project end date referenced in schedules or annexes'),
    (23, 'Contracted completion date'),
    (24, 'Timeline indicating project end'),
    (25, 'Planned date of project closure'),
    (26, 'Project finish date in agreement documentation'),
    (27, 'Project scheduled completion as per agreement'),
    (28, 'Project end date in header or metadata'),
    (29, 'Planned conclusion date mentioned in contract'),
    (30, 'End date of the engagement under this contract')
) AS v (position, query) ON true
WHERE f.key = 'planned_project_end_date';

-- 8. Price Escalation Clauses
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'price_escalation_clauses', 'Price Escalation Clauses', 'The specific terms in the contract that govern how and under what conditions the price of goods, services, or deliverables may increase over time. This may include escalation triggers, formulas, indices (e.g., CPI), thresholds, or periodic adjustments.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
price_escalation_clauses

Definition of price_escalation_clauses:
The specific terms in the contract that govern how and under what conditions the price of goods, services, or deliverables may increase over time. This may include escalation triggers, formulas, indices (e.g., CPI), thresholds, or periodic adjustments.
Extraction Rules:
Extract the clauses exactly as written in the contract text.
Include any numerical formulas, references to indices, percentages, or schedules.
Do not infer, summarize, or reinterpret the clauses.
If no price escalation clauses are present, return an empty string.
JSON Format:
{
"price_escalation_clauses": ""
}
Input Chunks:',
       8
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Price escalation clauses in the agreement'),
    (2, 'Contract section specifying price adjustments'),
    (3, 'Terms for price changes or escalation'),
    (4, 'Pricing escalation conditions in the contract'),
    (5, 'Agreement section on cost increase or adjustment'),
    (6, 'Clauses governing price revisions'),
    (7, 'Contract terms regarding inflation or indexation'),
    (8, 'Price adjustment provisions in the agreement'),
    (9, 'Escalation of fees or charges specified in contract'),
    (10, 'Conditions under which pricing may change'),
    (11, 'Contractual rules for modifying prices'),
    (12, 'Price change or escalation schedules'),
    (13, 'Provisions for adjusting payment amounts'),
    (14, 'Clause describing pricing updates over time'),
    (15, 'Agreed methodology for price escalation'),
    (16, 'Contract section detailing price variation'),
    (17, 'Terms for adjusting fees due to cost changes'),
    (18, 'Price escalation or revision clauses in contract'),
    (19, 'Pricing change rules referenced in agreement'),
    (20, 'Contract clauses on increasing charges'),
    (21, 'Escalation mechanism for contract prices'),
    (22, 'Fee adjustment provisions based on index or CPI'),
    (23, 'Contract terms covering price increases'),
    (24, 'Pricing escalation terms and conditions'),
    (25, 'Clauses on adjustment of contract value'),
    (26, 'Agreed price change triggers in the agreement'),
    (27, 'Contract section on escalation of rates'),
    (28, 'Rules for modifying project costs or fees'),
    (29, 'Price adjustment clauses for the customer'),
    (30, 'Methodology for increasing contract prices')
) AS v (position, query) ON true
WHERE f.key = 'price_escalation_clauses';

-- 9. Discounts
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'discounts', 'Discounts', 'The clauses or terms in the contract that describe any price reductions, rebates, promotional discounts, or special pricing arrangements applicable to the customer. This may include early payment discounts, volume-based discounts, or conditional rebates.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
discounts
Definition of discounts:
The clauses or terms in the contract that describe any price reductions, rebates, promotional discounts, or special pricing arrangements applicable to the customer. This may include early payment discounts, volume-based discounts, or conditional rebates.
Extraction Rules:
Extract the discount clauses exactly as written in the contract text.
Include any numerical percentages, amounts, formulas, conditions, or schedules.
Do not infer, summarize, or reinterpret the clauses.
If no discount clauses are present, return an empty string.
JSON Format:
{
"discounts": ""
}
Input Chunks:',
       9
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Discount clauses in the agreement'),
    (2, 'Contract section specifying discounts'),
    (3, 'Terms for price reductions or rebates'),
    (4, 'Discounts and promotional pricing in the contract'),
    (5, 'Agreement section on discount eligibility'),
    (6, 'Clauses governing customer discounts'),
    (7, 'Contract terms regarding rebates or markdowns'),
    (8, 'Discount provisions in the agreement'),
    (9, 'Conditions under which discounts apply'),
    (10, 'Contractual rules for applying discounts'),
    (11, 'Discount schedules or tables referenced in contract'),
    (12, 'Provisions for price reductions'),
    (13, 'Clause describing promotional or volume discounts'),
    (14, 'Agreed methodology for calculating discounts'),
    (15, 'Contract section detailing discount rules'),
    (16, 'Terms for applying early payment or volume discounts'),
    (17, 'Discount or rebate clauses in the agreement'),
    (18, 'Pricing adjustment rules for discounts'),
    (19, 'Contract clauses on promotional pricing'),
    (20, 'Discount mechanism for customer orders'),
    (21, 'Fee reduction provisions based on conditions'),
    (22, 'Contract terms covering price deductions'),
    (23, 'Discount application terms and conditions'),
    (24, 'Clauses on adjustment of invoice amounts for discounts'),
    (25, 'Agreed discount triggers in the agreement'),
    (26, 'Contract section on special pricing or discounts'),
    (27, 'Rules for applying contract-based discounts'),
    (28, 'Discount clauses for goods or services'),
    (29, 'Methodology for applying rebates or reductions'),
    (30, 'Customer discount terms in the agreement')
) AS v (position, query) ON true
WHERE f.key = 'discounts';

-- 10. Force Majeure Provisions
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'force_majeure_provisions', 'Force Majeure Provisions', 'The clauses in the contract that describe events or circumstances beyond the control of the parties that may excuse or delay performance, such as natural disasters, war, strikes, pandemics, or other extraordinary events.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
force_majeure_provisions

Definition of force_majeure_provisions:
The clauses in the contract that describe events or circumstances beyond the control of the parties that may excuse or delay performance, such as natural disasters, war, strikes, pandemics, or other extraordinary events.
Extraction Rules:
Extract the force majeure provisions exactly as written in the contract text.
Include all conditions, obligations, notification requirements, and remedies stated.
Do not infer, summarize, or reinterpret the clauses.
If no force majeure provisions are present, return an empty string.
JSON Format:
{
"force_majeure_provisions": ""
}
Input Chunks:',
       10
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Force majeure provisions in the agreement'),
    (2, 'Contract section specifying force majeure events'),
    (3, 'Clauses covering unforeseen circumstances'),
    (4, 'Terms regarding events beyond control of parties'),
    (5, 'Agreement section on force majeure conditions'),
    (6, 'Contract clauses for natural disasters or emergencies'),
    (7, 'Provisions excusing performance due to force majeure'),
    (8, 'Force majeure events and obligations in contract'),
    (9, 'Clauses on delay or non-performance due to extraordinary events'),
    (10, 'Contract section detailing force majeure occurrences'),
    (11, 'Conditions under which force majeure applies'),
    (12, 'Obligations suspended due to force majeure events'),
    (13, 'Events of force majeure and remedies'),
    (14, 'Contractual rules for unforeseeable events'),
    (15, 'Agreement terms for acts of God or emergencies'),
    (16, 'Force majeure notification and procedure clauses'),
    (17, 'Clauses covering war, strike, or natural calamities'),
    (18, 'Contract section on liability during force majeure'),
    (19, 'Exemption clauses for force majeure events'),
    (20, 'Procedures and remedies for force majeure situations'),
    (21, 'Contract terms regarding interruptions due to extraordinary events'),
    (22, 'Force majeure triggers and definitions in agreement'),
    (23, 'Suspension of obligations under force majeure'),
    (24, 'Force majeure notification and mitigation procedures'),
    (25, 'Contractual rights and responsibilities during force majeure'),
    (26, 'Clauses specifying events beyond reasonable control'),
    (27, 'Force majeure conditions in performance obligations'),
    (28, 'Contract provisions for extraordinary events'),
    (29, 'Exclusions or reliefs due to force majeure'),
    (30, 'Force majeure events referenced in schedules or annexes')
) AS v (position, query) ON true
WHERE f.key = 'force_majeure_provisions';

-- 11. Deliverables
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'deliverables', 'Deliverables', 'The specific goods, services, outputs, or work products that the contractor or service provider is required to provide under the contract. This may include items defined in the scope of work, schedules, statements of work, or annexes.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
deliverables

Definition of deliverables:
The specific goods, services, outputs, or work products that the contractor or service provider is required to provide under the contract. This may include items defined in the scope of work, schedules, statements of work, or annexes.
Extraction Rules:
Extract the deliverables exactly as written in the contract text.
Include all descriptions, quantities, milestones, or conditions as present.
Do not infer, summarize, or reformat.
If deliverables are not explicitly mentioned, return an empty string.
JSON Format:
{
"deliverables": ""
}
Input Chunks:',
       11
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Deliverables specified in the agreement'),
    (2, 'Contract section listing deliverables'),
    (3, 'Description of project deliverables in the contract'),
    (4, 'Agreement section detailing outputs or work products'),
    (5, 'Items or services to be delivered under the contract'),
    (6, 'Contractual obligations regarding deliverables'),
    (7, 'Deliverables defined in scope of work'),
    (8, 'Project outputs mentioned in the agreement'),
    (9, 'Schedule of deliverables in contract'),
    (10, 'List of work products to be provided'),
    (11, 'Contract clauses on deliverables and submission'),
    (12, 'Deliverables description in statement of work'),
    (13, 'Obligations to provide specific outputs'),
    (14, 'Contract section specifying deliverable requirements'),
    (15, 'Deliverables with due dates or milestones'),
    (16, 'Agreed outputs under the contract'),
    (17, 'Work products, items, or services to be delivered'),
    (18, 'Deliverables referenced in annexes or schedules'),
    (19, 'Contract section on project deliverables'),
    (20, 'Scope of work detailing expected deliverables'),
    (21, 'Deliverable obligations for the contractor'),
    (22, 'Agreement terms on deliverable acceptance'),
    (23, 'Deliverables mentioned in milestones or phases'),
    (24, 'Outputs required by the agreement'),
    (25, 'Deliverables and submission requirements in contract'),
    (26, 'Deliverables for client or customer under agreement'),
    (27, 'Contractual schedule of outputs'),
    (28, 'Project deliverables and descriptions'),
    (29, 'Obligations to deliver goods or services'),
    (30, 'Deliverables as per contract scope and terms')
) AS v (position, query) ON true
WHERE f.key = 'deliverables';

-- 12. Penalties
INSERT INTO fields (field_set_id, key, label, description, value_type, user_prompt, position)
SELECT id, 'penalties', 'Penalties', 'The clauses in the contract that specify fines, liquidated damages, or other consequences imposed on a party for non-performance, breach, delay, or failure to meet contractual obligations.', 'text',
       'Task: From the given contract text chunks, extract the following fields:
penalties

Definition of penalties:
The clauses in the contract that specify fines, liquidated damages, or other consequences imposed on a party for non-performance, breach, delay, or failure to meet contractual obligations.
Extraction Rules:
Extract the penalty clauses exactly as written in the contract text.
Include all amounts, formulas, percentages, or conditions stated.
Do not infer, summarize, or reinterpret the clauses.
If no penalties are mentioned, return an empty string.
JSON Format:
{
"penalties": ""
}
Input Chunks:',
       12
FROM field_sets WHERE name = 'contract_fields' AND version = 1;
INSERT INTO field_queries (field_id, position, query)
SELECT f.id, v.position, v.query
FROM fields f JOIN field_sets s ON s.id = f.field_set_id AND s.name = 'contract_fields' AND s.version = 1
JOIN (VALUES
    (1, 'Penalties specified in the agreement'),
    (2, 'Contract section detailing penalties'),
    (3, 'Clauses on fines or liquidated damages'),
    (4, 'Terms regarding consequences of non-performance'),
    (5, 'Agreement section on breach penalties'),
    (6, 'Contractual obligations and associated penalties'),
    (7, 'Penalties for delays in deliverables'),
    (8, 'Contract clauses for late performance'),
    (9, 'Financial penalties or sanctions in agreement'),
    (10, 'Contract section outlining penalty provisions'),
    (11, 'Conditions under which penalties apply'),
    (12, 'Liquidated damages or fines in the contract'),
    (13, 'Penalties for failure to meet contractual obligations'),
    (14, 'Clauses covering defaults and associated penalties'),
    (15, 'Contractual rules for non-compliance'),
    (16, 'Agreed penalties for breach of contract'),
    (17, 'Penalty amounts or formulas mentioned in agreement'),
    (18, 'Contract section on damages and penalties'),
    (19, 'Penalties linked to performance milestones'),
    (20, 'Financial consequences of non-fulfillment'),
    (21, 'Sanctions for delay, non-delivery, or breach'),
    (22, 'Penalty provisions in schedules or annexes'),
    (23, 'Contract section on remedial penalties'),
    (24, 'Rules for calculating contract penalties'),
    (25, 'Clauses on termination penalties'),
    (26, 'Penalty triggers in agreement terms'),
    (27, 'Contract clauses for fines and corrective actions'),
    (28, 'Obligations and associated penalties'),
    (29, 'Contractual consequences for violation'),
    (30, 'Penalties and remedies under the contract')
) AS v (position, query) ON true
WHERE f.key = 'penalties';

-- Default pipeline: all RAG configs in order, judge on
INSERT INTO pipeline_configs (name, description, decomposition_config_id, index_config_id, field_set_id,
                              extraction_profile_id, extraction_prompt_id, judge_enabled, judge_profile_id, judge_prompt_id, is_default)
SELECT 'default', 'Prototype setup: RAG01-RAG07, llama3.1:8b extraction and judge',
       (SELECT id FROM decomposition_configs WHERE name = 'default'),
       (SELECT id FROM index_configs WHERE name = 'default'),
       (SELECT id FROM field_sets WHERE name = 'contract_fields' AND version = 1),
       (SELECT id FROM model_profiles WHERE name = 'extraction-default'),
       (SELECT id FROM prompt_templates WHERE name = 'extraction_system' AND version = 1),
       true,
       (SELECT id FROM model_profiles WHERE name = 'judge-default'),
       (SELECT id FROM prompt_templates WHERE name = 'judge_system' AND version = 1),
       true;

INSERT INTO pipeline_config_retrievals (pipeline_config_id, retrieval_config_id, position)
SELECT p.id, r.id, row_number() OVER (ORDER BY r.name)
FROM pipeline_configs p CROSS JOIN retrieval_configs r
WHERE p.name = 'default';

COMMIT;
