-- Default configuration for ContractExtraction. Applied after schema.sql on an empty database.
-- Values come from the prototype (DocumentExtraction): search configs and system prompts.
-- The fields and contract types come from docs/contract_types_and_fields.md via seed_catalogue.sql,
-- which is generated and applied after this file.
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
    ('extraction-default',     'Field extraction with llama3.1:8b',       0.2, 0.2, 20),
    ('judge-default',          'LLM judge with llama3.1:8b',              0.1, 0.8, 100),
    ('classification-default', 'Contract type detection with llama3.1:8b', 0.0, 0.2, 20)
) AS v (name, description, temperature, top_p, top_k)
JOIN llm_models m ON m.name = 'llama3.1:8b' AND m.kind = 'chat';

-- System prompts
INSERT INTO prompt_templates (name, version, role, body) VALUES
    ('classification_system', 1, 'classification_system', 'You identify what kind of contract a document is.
Always follow these rules:
1. Decide from the document text only: its title, the parties, the recitals and what the document itself does.
2. List a type only if the document itself is that kind of contract, not when it merely mentions or refers to one
   (an SOW that refers to its master agreement is an SOW, not an MSA).
3. A document can be several types when it contains several agreements (e.g. an MSA with an SOW attached).
4. Confidence is between 0 and 1. Use the key "other" when no listed type fits.
5. Return output strictly in JSON format with no extra commentary.'),
    ('extraction_system', 1, 'extraction_system', 'You are a precise information extraction assistant.
Always follow these rules:
1. Only extract values exactly as they appear in the text.
2. If a field is not present, return null for it.
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

-- Contract fields: the set is created here and filled by seed_catalogue.sql.
INSERT INTO field_sets (name, version, description)
VALUES ('contract_fields', 1, 'Contract types and their fields (docs/contract_types_and_fields.md)');

-- Default pipeline: detect the contract type, then its fields under all RAG configs in order, judge on
INSERT INTO pipeline_configs (name, description, decomposition_config_id, index_config_id, field_set_id,
                              extraction_profile_id, extraction_prompt_id, judge_enabled, judge_profile_id, judge_prompt_id,
                              classification_enabled, classification_profile_id, classification_prompt_id, is_default)
SELECT 'default', 'Contract type detection, then RAG01-RAG07, llama3.1:8b extraction and judge',
       (SELECT id FROM decomposition_configs WHERE name = 'default'),
       (SELECT id FROM index_configs WHERE name = 'default'),
       (SELECT id FROM field_sets WHERE name = 'contract_fields' AND version = 1),
       (SELECT id FROM model_profiles WHERE name = 'extraction-default'),
       (SELECT id FROM prompt_templates WHERE name = 'extraction_system' AND version = 1),
       true,
       (SELECT id FROM model_profiles WHERE name = 'judge-default'),
       (SELECT id FROM prompt_templates WHERE name = 'judge_system' AND version = 1),
       true,
       (SELECT id FROM model_profiles WHERE name = 'classification-default'),
       (SELECT id FROM prompt_templates WHERE name = 'classification_system' AND version = 1),
       true;

INSERT INTO pipeline_config_retrievals (pipeline_config_id, retrieval_config_id, position)
SELECT p.id, r.id, row_number() OVER (ORDER BY r.name)
FROM pipeline_configs p CROSS JOIN retrieval_configs r
WHERE p.name = 'default';

COMMIT;
