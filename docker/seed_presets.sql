-- Preset configurations: low-cost OpenRouter models, more RAG configs and ready-made pipelines.
-- Applied after seed.sql and seed_catalogue.sql on an empty database. Every insert skips rows that
-- already exist, so `scripts/dev.sh presets` can also apply it to a running database without a reset.
--
-- OpenRouter pipelines need OPENROUTER_API_KEY and the provider enabled
-- (`contract-extraction providers set openrouter --enable`); until then they list with an error.
-- Models are picked for price (at most $0.10 per million input tokens) and JSON-mode support; prices are
-- OpenRouter's list prices in USD per million tokens (October 2026) and only feed llm_calls.cost_usd.
-- Embeddings stay on the local nomic-embed-text, so the existing vector indexes are reused.

BEGIN;

-- OpenRouter chat models
INSERT INTO llm_models (provider_id, name, kind, context_window, input_cost_per_mtok, output_cost_per_mtok)
SELECT p.id, m.name, 'chat', m.context_window, m.input_cost, m.output_cost
FROM llm_providers p
JOIN (VALUES
    -- Same model as the local llama3.1:8b: hosted baseline.
    ('meta-llama/llama-3.1-8b-instruct',         131072,  0.050, 0.080),
    ('qwen/qwen3-30b-a3b-instruct-2507',         262144,  0.090, 0.300),
    ('google/gemma-4-26b-a4b-it',                262144,  0.068, 0.225),
    -- Hybrid reasoning model; its profiles turn reasoning off.
    ('deepseek/deepseek-v4.1-flash',             1048576, 0.055, 0.144),
    ('google/gemini-2.5-flash-lite',             1048576, 0.100, 0.400),
    ('anthropic/claude-haiku-5.5',               1000000, 0.100, 0.500),
    -- Reasoning model; reasoning tokens count against max_tokens, so its profile leaves room for them.
    ('openai/gpt-6-luna',                        1050000, 0.100, 0.500)
) AS m (name, context_window, input_cost, output_cost) ON true
WHERE p.key = 'openrouter'
ON CONFLICT (provider_id, name, kind) DO NOTHING;

-- Model profiles. OpenRouter profiles leave top_k and num_ctx unset (Ollama-only settings).
-- Group profiles answer up to 8 fields per call and get a larger max_tokens.
INSERT INTO model_profiles (name, description, model_id, temperature, top_p, top_k, max_tokens, num_ctx,
                            json_mode, timeout_seconds, extra)
SELECT v.name, v.description, m.id, v.temperature, v.top_p, v.top_k, v.max_tokens, v.num_ctx, true, v.timeout, v.extra::jsonb
FROM (VALUES
    ('extraction-group-local',             'Group extraction with llama3.1:8b (local)',
     'llama3.1:8b',                              0.2, 0.2, 20,           3072, 12288,         300, '{}'),
    ('extraction-or-llama31-8b',           'Field extraction with Llama 3.1 8B via OpenRouter',
     'meta-llama/llama-3.1-8b-instruct',         0.2, 0.2, NULL::integer, 1024, NULL::integer, 120, '{}'),
    ('judge-or-llama31-8b',                'LLM judge with Llama 3.1 8B via OpenRouter',
     'meta-llama/llama-3.1-8b-instruct',         0.1, 0.8, NULL,          512, NULL,           120, '{}'),
    ('classification-or-llama31-8b',       'Contract type detection with Llama 3.1 8B via OpenRouter',
     'meta-llama/llama-3.1-8b-instruct',         0.0, 0.2, NULL,          512, NULL,           120, '{}'),
    ('extraction-or-qwen3-30b',            'Field extraction with Qwen3 30B A3B Instruct via OpenRouter',
     'qwen/qwen3-30b-a3b-instruct-2507',         0.1, NULL::numeric, NULL, 1024, NULL,         120, '{}'),
    ('extraction-or-gemma4-26b',           'Field extraction with Gemma 4 26B A4B via OpenRouter',
     'google/gemma-4-26b-a4b-it',                0.1, NULL,          NULL, 1024, NULL,         120, '{}'),
    ('extraction-group-or-deepseek-flash', 'Group extraction with DeepSeek V4.1 Flash via OpenRouter, reasoning off',
     'deepseek/deepseek-v4.1-flash',             0.1, NULL,          NULL, 4096, NULL,         180,
     '{"params": {"reasoning": {"enabled": false}}}'),
    ('extraction-group-or-gemini-lite',    'Group extraction with Gemini 2.5 Flash-Lite via OpenRouter',
     'google/gemini-2.5-flash-lite',             0.1, NULL,          NULL, 4096, NULL,         180, '{}'),
    ('classification-or-gemini-lite',      'Contract type detection with Gemini 2.5 Flash-Lite via OpenRouter',
     'google/gemini-2.5-flash-lite',             0.0, NULL,          NULL,  512, NULL,         120, '{}'),
    ('judge-or-gemini-lite',               'LLM judge with Gemini 2.5 Flash-Lite via OpenRouter',
     'google/gemini-2.5-flash-lite',             0.1, NULL,          NULL,  512, NULL,         120, '{}'),
    ('extraction-or-haiku',                'Field extraction with Claude Haiku 5.5 via OpenRouter',
     'anthropic/claude-haiku-5.5',               0.1, NULL,          NULL, 1024, NULL,         120, '{}'),
    ('classification-or-haiku',            'Contract type detection with Claude Haiku 5.5 via OpenRouter',
     'anthropic/claude-haiku-5.5',               0.0, NULL,          NULL,  512, NULL,         120, '{}'),
    ('judge-or-haiku',                     'LLM judge with Claude Haiku 5.5 via OpenRouter',
     'anthropic/claude-haiku-5.5',               0.1, NULL,          NULL,  512, NULL,         120, '{}'),
    ('judge-or-gpt6-luna',                 'LLM judge with GPT-6 Luna via OpenRouter, low reasoning effort',
     'openai/gpt-6-luna',                        1.0, NULL,          NULL, 4096, NULL,         180,
     '{"params": {"reasoning": {"effort": "low"}}}')
) AS v (name, description, model, temperature, top_p, top_k, max_tokens, num_ctx, timeout, extra)
JOIN llm_models m ON m.name = v.model AND m.kind = 'chat'
ON CONFLICT (name) DO NOTHING;

-- More RAG retrieval configurations, all hybrid (dense + keyword search fused).
INSERT INTO retrieval_configs (name, description, top_k, score_threshold, query_expansion, per_query_top, min_score,
                               keyword_search, anchor_chunks) VALUES
    ('RAG08', 'hybrid: top 8, threshold 0.5, with query expansion, 4 hits per query, 2 anchor chunks',
     8, 0.5, true, 4, 0.30, true, 2),
    -- Small evidence for the local 8B model's context.
    ('RAG09', 'hybrid tight: top 3, threshold 0.6, with query expansion, 1 anchor chunk',
     3, 0.6, true, 3, 0.30, true, 1),
    -- High recall for long-context cloud models and group extraction.
    ('RAG10', 'hybrid high recall: top 15, threshold 0.4, with query expansion, 5 hits per query, 3 anchor chunks',
     15, 0.4, true, 5, 0.25, true, 3),
    -- RAG07 without query expansion: isolates what the expansion queries add once keyword search is on.
    ('RAG11', 'hybrid: top 5, threshold 0.5, without query expansion, 2 anchor chunks',
     5, 0.5, false, 3, 0.30, true, 2)
ON CONFLICT (name) DO NOTHING;

-- Pipelines. All use the default decomposition and index, the contract_fields set and version 1 of the
-- system prompts. A NULL judge or classification profile turns that stage off.
INSERT INTO pipeline_configs (name, description, decomposition_config_id, index_config_id, field_set_id,
                              extraction_profile_id, extraction_prompt_id, judge_enabled, judge_profile_id, judge_prompt_id,
                              judge_parallel, classification_enabled, classification_profile_id, classification_prompt_id,
                              min_priority, extraction_granularity)
SELECT v.name, v.description, dc.id, ic.id, fs.id, ep.id, xp.id,
       jp.id IS NOT NULL, jp.id, CASE WHEN jp.id IS NOT NULL THEN jpr.id END, v.judge_parallel,
       cp.id IS NOT NULL, cp.id, CASE WHEN cp.id IS NOT NULL THEN cpr.id END,
       v.min_priority, v.granularity
FROM (VALUES
    ('local-fast',       'Local llama3.1:8b, type detection, group extraction under RAG07, no judge: a quick first pass',
     'extraction-group-local', NULL, 'classification-default', false, 'P3', 'group'),
    ('local-hybrid',     'Local llama3.1:8b, type detection, field extraction under the hybrid RAG09 and RAG07, judge on',
     'extraction-default', 'judge-default', 'classification-default', false, 'P3', 'field'),
    ('or-llama31-8b',    'The default pipeline (RAG01-RAG07) with Llama 3.1 8B hosted on OpenRouter: local vs hosted',
     'extraction-or-llama31-8b', 'judge-or-llama31-8b', 'classification-or-llama31-8b', true, 'P3', 'field'),
    ('or-budget',        'Cheapest cloud run: DeepSeek V4.1 Flash group extraction under RAG10, Gemini Flash-Lite judge',
     'extraction-group-or-deepseek-flash', 'judge-or-gemini-lite', 'classification-or-gemini-lite', true, 'P3', 'group'),
    ('or-qwen3',         'Qwen3 30B field extraction under RAG08 and RAG07, Claude Haiku judge',
     'extraction-or-qwen3-30b', 'judge-or-haiku', 'classification-or-gemini-lite', true, 'P3', 'field'),
    ('or-gemma4',        'Gemma 4 26B field extraction under RAG08 and RAG07, GPT-6 Luna judge',
     'extraction-or-gemma4-26b',    'judge-or-gpt6-luna', 'classification-or-gemini-lite', true, 'P3', 'field'),
    ('or-haiku',         'Claude Haiku 5.5 detection and field extraction under RAG08 and RAG07, GPT-6 Luna judge',
     'extraction-or-haiku', 'judge-or-gpt6-luna', 'classification-or-haiku', true, 'P3', 'field'),
    ('or-rag-sweep',     'Qwen3 30B under every hybrid RAG config (RAG07-RAG11), Claude Haiku judge: compare retrieval',
     'extraction-or-qwen3-30b', 'judge-or-haiku', 'classification-or-gemini-lite', true, 'P3', 'field'),
    ('or-p1-triage',     'P1 fields only (direct financial, time or exit exposure), Gemini Flash-Lite group extraction, no judge',
     'extraction-group-or-gemini-lite', NULL, 'classification-or-gemini-lite', false, 'P1', 'group')
) AS v (name, description, extraction_profile, judge_profile, classification_profile, judge_parallel, min_priority, granularity)
JOIN decomposition_configs dc ON dc.name = 'default'
JOIN index_configs ic ON ic.name = 'default'
JOIN field_sets fs ON fs.name = 'contract_fields' AND fs.version = 1
JOIN model_profiles ep ON ep.name = v.extraction_profile
LEFT JOIN model_profiles jp ON jp.name = v.judge_profile
LEFT JOIN model_profiles cp ON cp.name = v.classification_profile
JOIN prompt_templates xp ON xp.name = 'extraction_system' AND xp.version = 1
JOIN prompt_templates jpr ON jpr.name = 'judge_system' AND jpr.version = 1
JOIN prompt_templates cpr ON cpr.name = 'classification_system' AND cpr.version = 1
ON CONFLICT (name) DO NOTHING;

-- RAG configs per pipeline, in priority order (position 1 = preferred answer).
INSERT INTO pipeline_config_retrievals (pipeline_config_id, retrieval_config_id, position)
SELECT p.id, r.id, v.position
FROM (VALUES
    ('local-fast', 'RAG07', 1),
    ('local-hybrid', 'RAG09', 1), ('local-hybrid', 'RAG07', 2),
    ('or-llama31-8b', 'RAG01', 1), ('or-llama31-8b', 'RAG02', 2), ('or-llama31-8b', 'RAG03', 3),
    ('or-llama31-8b', 'RAG04', 4), ('or-llama31-8b', 'RAG05', 5), ('or-llama31-8b', 'RAG06', 6),
    ('or-llama31-8b', 'RAG07', 7),
    ('or-budget', 'RAG10', 1),
    ('or-qwen3', 'RAG08', 1), ('or-qwen3', 'RAG07', 2),
    ('or-gemma4', 'RAG08', 1), ('or-gemma4', 'RAG07', 2),
    ('or-haiku', 'RAG08', 1), ('or-haiku', 'RAG07', 2),
    ('or-rag-sweep', 'RAG08', 1), ('or-rag-sweep', 'RAG07', 2), ('or-rag-sweep', 'RAG09', 3),
    ('or-rag-sweep', 'RAG10', 4), ('or-rag-sweep', 'RAG11', 5),
    ('or-p1-triage', 'RAG08', 1)
) AS v (pipeline, retrieval, position)
JOIN pipeline_configs p ON p.name = v.pipeline
JOIN retrieval_configs r ON r.name = v.retrieval
-- A pipeline that already had its RAG configs (an earlier application, or edited since) is left alone.
WHERE NOT EXISTS (SELECT 1 FROM pipeline_config_retrievals x WHERE x.pipeline_config_id = p.id)
ON CONFLICT DO NOTHING;

COMMIT;
