import type { Catalog } from '@/api/config'
import type {
  DocumentDetail,
  DocumentOut,
  FieldResultDetail,
  GroundTruthOut,
  PipelineOut,
  RunOut,
  RunResults,
  RunSummary,
} from '@/api/client'

export const DOC_ID = '11111111-1111-1111-1111-111111111111'
export const RUN_ID = '22222222-2222-2222-2222-222222222222'
export const DEC_ID = '33333333-3333-3333-3333-333333333333'
export const RESULT_A = '44444444-4444-4444-4444-444444444441'
export const RESULT_B = '44444444-4444-4444-4444-444444444442'
export const RESULT_C = '44444444-4444-4444-4444-444444444443'
export const FIELD_CUSTOMER = '88888888-8888-8888-8888-888888888881'
export const FIELD_PAYMENT = '88888888-8888-8888-8888-888888888882'
export const FIELD_PARTIES = '88888888-8888-8888-8888-888888888883'

export function runSummary(over: Partial<RunSummary> = {}): RunSummary {
  return {
    id: RUN_ID,
    document_id: DOC_ID,
    kind: 'full',
    state: 'succeeded',
    stage: null,
    progress_done: 2,
    progress_total: 2,
    error: null,
    queued_at: '2026-10-14T10:00:00Z',
    started_at: '2026-10-14T10:00:01Z',
    finished_at: '2026-10-14T10:01:00Z',
    ...over,
  }
}

export function run(over: Partial<RunOut> = {}): RunOut {
  return {
    ...runSummary(over),
    pipeline: 'default',
    options: {},
    worker_id: 'worker-1',
    heartbeat_at: null,
    cancel_requested: false,
    attempts: 1,
    decomposition_id: DEC_ID,
    vector_index_id: null,
    ...over,
  }
}

export function document(over: Partial<DocumentOut> = {}): DocumentOut {
  return {
    id: DOC_ID,
    code: 'DOC001',
    title: null,
    original_filename: 'sample.pdf',
    mime_type: 'application/pdf',
    sha256: 'abc',
    size_bytes: 2048,
    page_count: 3,
    tags: [],
    created_at: '2026-10-14T09:00:00Z',
    latest_run: null,
    ...over,
  }
}

export function documentDetail(over: Partial<DocumentDetail> = {}): DocumentDetail {
  return { ...document(over), decompositions: [], runs: [], ...over }
}

export const pipelines: PipelineOut[] = [
  {
    name: 'default',
    is_default: true,
    description: 'Seeded pipeline',
    error: null,
    decomposition: 'pymupdf (pymupdf, md)',
    index: 'default (2000/300, qdrant)',
    embedding_model: 'nomic-embed-text',
    extraction: { name: 'extract', model: 'llama3.1:8b', provider: 'ollama-local', temperature: '0.0' },
    judge: { name: 'judge', model: 'llama3.1:8b', provider: 'ollama-local', temperature: '0.1' },
    retrievals: [
      { name: 'RAG01', top_k: 3, score_threshold: '0.5', query_expansion: false, per_query_top: 3, min_score: '0.0' },
      { name: 'RAG02', top_k: 5, score_threshold: '0.4', query_expansion: true, per_query_top: 5, min_score: '0.0' },
    ],
    fields: [
      { key: 'customer_name', label: 'Customer name', description: null, value_type: 'text', query_count: 2 },
      { key: 'payment_terms', label: 'Payment terms', description: null, value_type: 'text', query_count: 3 },
    ],
  },
]

export const results: RunResults = {
  run: run(),
  best: [
    {
      field_id: FIELD_CUSTOMER,
      field_key: 'customer_name',
      field_label: 'Customer name',
      value_type: 'text',
      value: 'Acme GmbH',
      status: 'extracted',
      retrieval_config: 'RAG01',
      verdict: 'PASS',
      issue: 'NONE',
      explanation: 'Named in the preamble.',
      field_result_id: RESULT_A,
      expected_value: 'acme gmbh',
      exact_match: true,
    },
    {
      field_id: FIELD_PAYMENT,
      field_key: 'payment_terms',
      field_label: 'Payment terms',
      value_type: 'text',
      value: null,
      status: 'not_found',
      retrieval_config: 'RAG01',
      verdict: null,
      issue: null,
      explanation: null,
      field_result_id: RESULT_B,
      expected_value: null,
      exact_match: null,
    },
  ],
  evaluation: { fields: 2, labelled: 1, matched: 1 },
  results: [
    {
      id: RESULT_A,
      field_key: 'customer_name',
      field_label: 'Customer name',
      retrieval_config: 'RAG01',
      status: 'extracted',
      value: 'Acme GmbH',
      error: null,
      extraction_ms: 1200,
      verdict: 'PASS',
      issue: 'NONE',
      created_at: '2026-10-14T10:00:30Z',
    },
    {
      id: RESULT_B,
      field_key: 'payment_terms',
      field_label: 'Payment terms',
      retrieval_config: 'RAG01',
      status: 'not_found',
      value: null,
      error: null,
      extraction_ms: 900,
      verdict: null,
      issue: null,
      created_at: '2026-10-14T10:00:40Z',
    },
    {
      id: RESULT_C,
      field_key: 'customer_name',
      field_label: 'Customer name',
      retrieval_config: 'RAG02',
      status: 'extracted',
      value: 'ACME',
      error: null,
      extraction_ms: 1100,
      verdict: 'FAIL',
      issue: 'INCOMPLETE',
      created_at: '2026-10-14T10:00:50Z',
    },
  ],
}

export const groundTruth: GroundTruthOut = {
  field_set: { id: '99999999-9999-9999-9999-999999999999', name: 'contract_fields', version: 1 },
  items: [
    {
      field_id: FIELD_CUSTOMER,
      field_key: 'customer_name',
      field_label: 'Customer name',
      value_type: 'text',
      expected_value: 'acme gmbh',
      notes: 'from the preamble',
      updated_at: '2026-10-14T11:00:00Z',
    },
    {
      field_id: FIELD_PAYMENT,
      field_key: 'payment_terms',
      field_label: 'Payment terms',
      value_type: 'text',
      expected_value: null,
      notes: null,
      updated_at: null,
    },
    {
      field_id: FIELD_PARTIES,
      field_key: 'parties',
      field_label: 'Parties',
      value_type: 'list',
      expected_value: '',
      notes: null,
      updated_at: '2026-10-14T11:00:00Z',
    },
  ],
}

const MODEL_CHAT = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa1'
const MODEL_EMBED = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaa2'

export const catalog: Catalog = {
  providers: [
    {
      key: 'ollama-local',
      kind: 'ollama',
      base_url: 'http://localhost:11434',
      api_key_env: null,
      is_enabled: true,
      models: [
        { id: MODEL_CHAT, name: 'llama3.1:8b', kind: 'chat', context_window: 131072, embedding_dimension: null, input_cost_per_mtok: null, output_cost_per_mtok: null, is_enabled: true },
        { id: MODEL_EMBED, name: 'nomic-embed-text', kind: 'embedding', context_window: null, embedding_dimension: 768, input_cost_per_mtok: null, output_cost_per_mtok: null, is_enabled: true },
      ],
    },
  ],
  profiles: [
    { name: 'extraction-default', description: null, model_id: MODEL_CHAT, model: 'llama3.1:8b', provider: 'ollama-local', temperature: '0.200', top_p: '0.200', top_k: 20, max_tokens: null, num_ctx: 8192, json_mode: true, timeout_seconds: 600 },
    { name: 'judge-default', description: null, model_id: MODEL_CHAT, model: 'llama3.1:8b', provider: 'ollama-local', temperature: '0.100', top_p: '0.800', top_k: 100, max_tokens: null, num_ctx: 8192, json_mode: true, timeout_seconds: 600 },
  ],
  prompts: [
    { name: 'extraction_system', version: 1, role: 'extraction_system', body: 'You are precise.', notes: null, is_active: true, created_at: '2026-10-14T09:00:00Z' },
    { name: 'judge_system', version: 1, role: 'judge_system', body: 'You judge.', notes: null, is_active: true, created_at: '2026-10-14T09:00:00Z' },
  ],
  decompositions: [
    { name: 'default', description: null, method: 'pymupdf', text_format: 'md', keep_invisible_text: true, remove_headers_footers: true, ocr_language: 'eng', dpi: 200 },
  ],
  indexes: [
    { name: 'default', description: null, embedding_model_id: MODEL_EMBED, embedding_model: 'nomic-embed-text', chunk_size: 2000, chunk_overlap: 300, vector_store: 'qdrant', distance: 'cosine', batch_size: 32 },
  ],
  retrievals: [
    { name: 'RAG01', description: null, top_k: 10, score_threshold: '0.500', query_expansion: true, per_query_top: 3, min_score: '0.300' },
    { name: 'RAG02', description: null, top_k: 5, score_threshold: '0.500', query_expansion: true, per_query_top: 3, min_score: '0.300' },
    { name: 'RAG03', description: 'spare', top_k: 3, score_threshold: '0.500', query_expansion: false, per_query_top: 3, min_score: '0.300' },
  ],
  field_sets: [
    {
      name: 'contract_fields',
      version: 1,
      description: null,
      fields: [
        {
          id: FIELD_CUSTOMER, key: 'customer_name', label: 'Customer name', description: null, value_type: 'text',
          type_spec: null, value_schema: {}, priority: 'P1', user_prompt: 'Find the customer.', position: 1, is_enabled: true,
          queries: ['customer', 'buyer'],
        },
      ],
    },
  ],
  pipelines: [
    {
      name: 'default',
      description: 'Seeded',
      is_default: true,
      decomposition: 'default',
      index: 'default',
      field_set: { name: 'contract_fields', version: 1 },
      extraction_profile: 'extraction-default',
      extraction_prompt: { name: 'extraction_system', version: 1 },
      judge_enabled: true,
      judge_profile: 'judge-default',
      judge_prompt: { name: 'judge_system', version: 1 },
      judge_parallel: false,
      retrievals: ['RAG01', 'RAG02'],
      error: null,
    },
    {
      name: 'broken',
      description: null,
      is_default: false,
      decomposition: 'default',
      index: 'default',
      field_set: { name: 'contract_fields', version: 1 },
      extraction_profile: 'extraction-default',
      extraction_prompt: { name: 'extraction_system', version: 1 },
      judge_enabled: false,
      judge_profile: null,
      judge_prompt: null,
      judge_parallel: false,
      retrievals: ['RAG01'],
      error: "Model 'llama3.1:8b' (extraction) is disabled",
    },
  ],
}

export const fieldResult: FieldResultDetail = {
  ...results.results[0],
  raw_answer: '{"value": "Acme GmbH"}',
  reused_from: null,
  hits: [
    {
      rank: 1,
      score: 0.8123,
      page: 2,
      matched_query: 'customer',
      chunk_id: '55555555-5555-5555-5555-555555555555',
      text: 'This agreement is made with Acme GmbH.',
    },
  ],
  llm_calls: [
    {
      id: '66666666-6666-6666-6666-666666666666',
      purpose: 'extraction',
      provider_key: 'ollama-local',
      model_name: 'llama3.1:8b',
      params: { temperature: 0 },
      system_prompt: 'Extract the field.',
      user_prompt: 'Who is the customer?',
      response: '{"value": "Acme GmbH"}',
      status: 'ok',
      error: null,
      prompt_tokens: 812,
      completion_tokens: 12,
      latency_ms: 1150,
      cost_usd: null,
      created_at: '2026-10-14T10:00:29Z',
    },
  ],
  judgements: [
    { verdict: 'PASS', issue: 'NONE', explanation: 'Supported by the evidence.', llm_call_id: null, created_at: '2026-10-14T10:00:30Z' },
  ],
}
