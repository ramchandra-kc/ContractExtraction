-- ContractExtraction database schema (PostgreSQL 16).
--
-- Applied automatically when the Postgres volume is empty (see docker-compose.yml).
-- There are no migrations: change this file, then recreate the database with
--   docker compose -f docker/docker-compose.yml down -v && docker compose -f docker/docker-compose.yml up -d
--
-- Sections
--   0. Helpers
--   1. Model & RAG configuration   (providers, models, profiles, prompts, decomposition, indexing, retrieval, fields, pipelines)
--   2. Documents & artifacts       (documents, decompositions, pages, images, vector indexes, chunks)
--   3. Runs & results              (experiments, runs, events, field results, retrieval hits, LLM calls, judgements)
--   4. Evaluation                  (ground truth, views)
--
-- Conventions
--   * uuid primary keys (gen_random_uuid), timestamptz everywhere.
--   * Status-like columns are text + named CHECK constraints, so new values need no type changes.
--   * Constraint names: pk_<table>, fk_<table>_<column>, uq_<table>_<columns>, ix_<table>_<columns>, ck_<table>_<rule>.
--   * Configuration rows are editable; every run stores the resolved configuration in runs.config_snapshot.
--     Configuration referenced by results cannot be deleted (default NO ACTION foreign keys).
--   * Deleting a document deletes everything derived from it (ON DELETE CASCADE).
--   * No secrets are stored: providers name the environment variable that holds their API key.

BEGIN;

-- =====================================================================================================
-- 0. Helpers
-- =====================================================================================================

CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- A JSON value without the object keys whose value is null or "" (at any depth, also inside list items), so an
-- answer that writes "" for an unknown key compares equal to a label that leaves it null.
CREATE FUNCTION jsonb_strip_empty(j jsonb) RETURNS jsonb
LANGUAGE plpgsql IMMUTABLE AS $$
BEGIN
    RETURN CASE jsonb_typeof(j)
        WHEN 'object' THEN coalesce(
            (SELECT jsonb_object_agg(key, jsonb_strip_empty(value)) FROM jsonb_each(j)
             WHERE value NOT IN ('null'::jsonb, '""'::jsonb)), '{}'::jsonb)
        WHEN 'array' THEN coalesce(
            (SELECT jsonb_agg(jsonb_strip_empty(value) ORDER BY n) FROM jsonb_array_elements(j) WITH ORDINALITY AS e(value, n)),
            '[]'::jsonb)
        ELSE j
    END;
END;
$$;

CREATE SEQUENCE document_code_seq;

-- DOC001, DOC002, ... DOC999, DOC1000, ...
CREATE FUNCTION next_document_code() RETURNS text
LANGUAGE plpgsql VOLATILE AS $$
DECLARE
    n bigint := nextval('document_code_seq');
BEGIN
    RETURN 'DOC' || lpad(n::text, greatest(3, length(n::text)), '0');
END;
$$;

-- =====================================================================================================
-- 1. Model & RAG configuration
-- =====================================================================================================

-- Where models are served from: a local Ollama, OpenRouter, or any OpenAI-compatible endpoint.
CREATE TABLE llm_providers (
    id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    key         text        NOT NULL,
    kind        text        NOT NULL,
    base_url    text        NOT NULL,
    -- Name of the environment variable that holds the API key (NULL when none is needed).
    api_key_env text,
    is_enabled  boolean     NOT NULL DEFAULT true,
    settings    jsonb       NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_llm_providers PRIMARY KEY (id),
    CONSTRAINT uq_llm_providers_key UNIQUE (key),
    CONSTRAINT ck_llm_providers_kind CHECK (kind IN ('ollama', 'openrouter', 'openai_compatible'))
);

CREATE TABLE llm_models (
    id                       uuid        NOT NULL DEFAULT gen_random_uuid(),
    provider_id              uuid        NOT NULL,
    name                     text        NOT NULL,
    kind                     text        NOT NULL,
    context_window           integer,
    embedding_dimension      integer,
    -- Prices in USD per one million tokens, used to compute llm_calls.cost_usd.
    input_cost_per_mtok      numeric(12, 6),
    output_cost_per_mtok     numeric(12, 6),
    is_enabled               boolean     NOT NULL DEFAULT true,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_llm_models PRIMARY KEY (id),
    CONSTRAINT fk_llm_models_provider_id FOREIGN KEY (provider_id) REFERENCES llm_providers (id),
    CONSTRAINT uq_llm_models_provider_id_name_kind UNIQUE (provider_id, name, kind),
    CONSTRAINT ck_llm_models_kind CHECK (kind IN ('chat', 'embedding', 'vision')),
    CONSTRAINT ck_llm_models_embedding_dimension CHECK (
        (kind = 'embedding') = (embedding_dimension IS NOT NULL) AND (embedding_dimension IS NULL OR embedding_dimension > 0)),
    CONSTRAINT ck_llm_models_context_window CHECK (context_window IS NULL OR context_window > 0),
    CONSTRAINT ck_llm_models_costs CHECK (
        (input_cost_per_mtok IS NULL OR input_cost_per_mtok >= 0) AND (output_cost_per_mtok IS NULL OR output_cost_per_mtok >= 0))
);

-- A model plus generation settings, e.g. "extraction-default" or "judge-default".
CREATE TABLE model_profiles (
    id              uuid         NOT NULL DEFAULT gen_random_uuid(),
    name            text         NOT NULL,
    description     text,
    model_id        uuid         NOT NULL,
    temperature     numeric(4, 3) NOT NULL DEFAULT 0.2,
    top_p           numeric(4, 3),
    top_k           integer,
    max_tokens      integer,
    -- Context window requested from the provider (Ollama silently truncates at its 4096 default).
    num_ctx         integer,
    json_mode       boolean      NOT NULL DEFAULT true,
    timeout_seconds integer      NOT NULL DEFAULT 180,
    extra           jsonb        NOT NULL DEFAULT '{}',
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_model_profiles PRIMARY KEY (id),
    CONSTRAINT fk_model_profiles_model_id FOREIGN KEY (model_id) REFERENCES llm_models (id),
    CONSTRAINT uq_model_profiles_name UNIQUE (name),
    CONSTRAINT ck_model_profiles_temperature CHECK (temperature BETWEEN 0 AND 2),
    CONSTRAINT ck_model_profiles_top_p CHECK (top_p IS NULL OR top_p BETWEEN 0 AND 1),
    CONSTRAINT ck_model_profiles_top_k CHECK (top_k IS NULL OR top_k > 0),
    CONSTRAINT ck_model_profiles_max_tokens CHECK (max_tokens IS NULL OR max_tokens > 0),
    CONSTRAINT ck_model_profiles_num_ctx CHECK (num_ctx IS NULL OR num_ctx > 0),
    CONSTRAINT ck_model_profiles_timeout_seconds CHECK (timeout_seconds > 0)
);
CREATE INDEX ix_model_profiles_model_id ON model_profiles (model_id);

-- System prompts, versioned. Only one version per name is active.
CREATE TABLE prompt_templates (
    id         uuid        NOT NULL DEFAULT gen_random_uuid(),
    name       text        NOT NULL,
    version    integer     NOT NULL,
    role       text        NOT NULL,
    body       text        NOT NULL,
    notes      text,
    is_active  boolean     NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_prompt_templates PRIMARY KEY (id),
    CONSTRAINT uq_prompt_templates_name_version UNIQUE (name, version),
    CONSTRAINT ck_prompt_templates_role CHECK (role IN ('extraction_system', 'judge_system', 'classification_system', 'caption')),
    CONSTRAINT ck_prompt_templates_version CHECK (version > 0)
);
CREATE UNIQUE INDEX uq_prompt_templates_active_name ON prompt_templates (name) WHERE is_active;

-- How a document is turned into page text. method applies to PDFs; images always use OCR.
CREATE TABLE decomposition_configs (
    id                     uuid        NOT NULL DEFAULT gen_random_uuid(),
    name                   text        NOT NULL,
    description            text,
    method                 text        NOT NULL DEFAULT 'pymupdf',
    text_format            text        NOT NULL DEFAULT 'md',
    keep_invisible_text    boolean     NOT NULL DEFAULT true,
    remove_headers_footers boolean     NOT NULL DEFAULT true,
    ocr_language           text        NOT NULL DEFAULT 'eng',
    dpi                    integer     NOT NULL DEFAULT 200,
    -- Vision model profile used to caption images; NULL disables captioning.
    caption_profile_id     uuid,
    options                jsonb       NOT NULL DEFAULT '{}',
    created_at             timestamptz NOT NULL DEFAULT now(),
    updated_at             timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_decomposition_configs PRIMARY KEY (id),
    CONSTRAINT fk_decomposition_configs_caption_profile_id FOREIGN KEY (caption_profile_id) REFERENCES model_profiles (id),
    CONSTRAINT uq_decomposition_configs_name UNIQUE (name),
    CONSTRAINT ck_decomposition_configs_method CHECK (method IN ('pymupdf', 'ocr', 'hybrid')),
    CONSTRAINT ck_decomposition_configs_text_format CHECK (text_format IN ('md', 'html')),
    CONSTRAINT ck_decomposition_configs_dpi CHECK (dpi BETWEEN 72 AND 1200)
);

-- How page text is chunked, embedded and stored as vectors.
CREATE TABLE index_configs (
    id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
    name               text        NOT NULL,
    description        text,
    embedding_model_id uuid        NOT NULL,
    chunk_size         integer     NOT NULL DEFAULT 2000,
    chunk_overlap      integer     NOT NULL DEFAULT 300,
    vector_store       text        NOT NULL DEFAULT 'qdrant',
    distance           text        NOT NULL DEFAULT 'cosine',
    batch_size         integer     NOT NULL DEFAULT 32,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_index_configs PRIMARY KEY (id),
    CONSTRAINT fk_index_configs_embedding_model_id FOREIGN KEY (embedding_model_id) REFERENCES llm_models (id),
    CONSTRAINT uq_index_configs_name UNIQUE (name),
    CONSTRAINT ck_index_configs_chunking CHECK (chunk_size > 0 AND chunk_overlap >= 0 AND chunk_overlap < chunk_size),
    CONSTRAINT ck_index_configs_vector_store CHECK (vector_store IN ('qdrant', 'memory')),
    CONSTRAINT ck_index_configs_distance CHECK (distance IN ('cosine', 'dot', 'euclid')),
    CONSTRAINT ck_index_configs_batch_size CHECK (batch_size > 0)
);

-- RAG retrieval settings (RAG01, RAG02, ...).
CREATE TABLE retrieval_configs (
    id              uuid         NOT NULL DEFAULT gen_random_uuid(),
    name            text         NOT NULL,
    description     text,
    -- Chunks passed to the extraction LLM.
    top_k           integer      NOT NULL,
    -- Minimum similarity for a chunk to count as relevant.
    score_threshold numeric(4, 3) NOT NULL,
    -- Search with the field's expansion queries (field_queries) instead of the field label only.
    query_expansion boolean      NOT NULL DEFAULT true,
    -- Hits fetched per expanded query before merging.
    per_query_top   integer      NOT NULL DEFAULT 3,
    -- Absolute score floor applied after merging.
    min_score       numeric(4, 3) NOT NULL DEFAULT 0.30,
    -- Also search by keyword (BM25) and fuse the rankings with the dense ones (reciprocal rank fusion).
    keyword_search  boolean      NOT NULL DEFAULT false,
    -- Opening/closing chunks added (beyond top_k) for fields with an anchor; 0 = off.
    anchor_chunks   integer      NOT NULL DEFAULT 0,
    -- Cross-encoder that re-scores the candidates against the field (fastembed model name); NULL = off.
    rerank_model      text,
    -- Fused candidates the reranker scores before the best top_k are kept.
    rerank_candidates integer    NOT NULL DEFAULT 30,
    created_at      timestamptz  NOT NULL DEFAULT now(),
    updated_at      timestamptz  NOT NULL DEFAULT now(),
    CONSTRAINT pk_retrieval_configs PRIMARY KEY (id),
    CONSTRAINT uq_retrieval_configs_name UNIQUE (name),
    CONSTRAINT ck_retrieval_configs_top_k CHECK (top_k > 0),
    CONSTRAINT ck_retrieval_configs_per_query_top CHECK (per_query_top > 0),
    CONSTRAINT ck_retrieval_configs_anchor_chunks CHECK (anchor_chunks >= 0),
    CONSTRAINT ck_retrieval_configs_rerank_candidates CHECK (rerank_candidates > 0),
    CONSTRAINT ck_retrieval_configs_scores CHECK (score_threshold BETWEEN 0 AND 1 AND min_score BETWEEN 0 AND 1)
);

-- A versioned set of fields to extract (e.g. contract_fields v1), with the contract types that use them.
CREATE TABLE field_sets (
    id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    name        text        NOT NULL,
    version     integer     NOT NULL,
    description text,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_field_sets PRIMARY KEY (id),
    CONSTRAINT uq_field_sets_name_version UNIQUE (name, version),
    CONSTRAINT ck_field_sets_version CHECK (version > 0)
);

CREATE TABLE fields (
    id           uuid        NOT NULL DEFAULT gen_random_uuid(),
    field_set_id uuid        NOT NULL,
    key          text        NOT NULL,
    label        text        NOT NULL,
    description  text,
    value_type   text        NOT NULL DEFAULT 'text',
    -- Type as written in docs/contract_types_and_fields.md, e.g. 'duration' or 'object: rate, cap' (NULL: not from the catalogue).
    type_spec    text,
    -- JSON Schema of the value: shown to the model and used to check answers ('{}' accepts anything).
    value_schema jsonb       NOT NULL DEFAULT '{}',
    -- Highest priority among the contract types using the field (P1 = direct financial, time or exit exposure).
    priority     text        NOT NULL DEFAULT 'P2',
    -- Hand-written extraction instructions; NULL uses the generic template built from the description and
    -- value schema. The retrieved context is appended at run time.
    user_prompt  text,
    position     integer     NOT NULL,
    is_enabled   boolean     NOT NULL DEFAULT true,
    -- Evidence always includes the document's opening (start) and/or closing (end) chunks when the RAG
    -- config sets anchor_chunks: for fields stated on the cover page or signature page.
    anchor       text,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_fields PRIMARY KEY (id),
    CONSTRAINT fk_fields_field_set_id FOREIGN KEY (field_set_id) REFERENCES field_sets (id) ON DELETE CASCADE,
    CONSTRAINT uq_fields_field_set_id_key UNIQUE (field_set_id, key),
    CONSTRAINT uq_fields_field_set_id_position UNIQUE (field_set_id, position),
    CONSTRAINT ck_fields_key CHECK (key ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT ck_fields_value_type CHECK (value_type IN ('text', 'date', 'number', 'money', 'list', 'boolean', 'json')),
    CONSTRAINT ck_fields_priority CHECK (priority IN ('P1', 'P2', 'P3')),
    CONSTRAINT ck_fields_value_schema CHECK (jsonb_typeof(value_schema) = 'object'),
    CONSTRAINT ck_fields_user_prompt CHECK (user_prompt IS NULL OR length(trim(user_prompt)) > 0),
    CONSTRAINT ck_fields_anchor CHECK (anchor IN ('start', 'end', 'both'))
);

-- Semantic-search queries used for a field when query expansion is on.
CREATE TABLE field_queries (
    id         uuid    NOT NULL DEFAULT gen_random_uuid(),
    field_id   uuid    NOT NULL,
    position   integer NOT NULL,
    query      text    NOT NULL,
    CONSTRAINT pk_field_queries PRIMARY KEY (id),
    CONSTRAINT fk_field_queries_field_id FOREIGN KEY (field_id) REFERENCES fields (id) ON DELETE CASCADE,
    CONSTRAINT uq_field_queries_field_id_position UNIQUE (field_id, position),
    CONSTRAINT ck_field_queries_query CHECK (length(trim(query)) > 0)
);

-- Contract types of a field set (NDA, MSA, SOW, ...). A run extracts the fields of the detected types;
-- the fallback type covers contracts that match none of them.
CREATE TABLE contract_types (
    id           uuid        NOT NULL DEFAULT gen_random_uuid(),
    field_set_id uuid        NOT NULL,
    key          text        NOT NULL,
    label        text        NOT NULL,
    -- How to recognise the type; shown to the classifier.
    description  text        NOT NULL,
    is_fallback  boolean     NOT NULL DEFAULT false,
    position     integer     NOT NULL,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_contract_types PRIMARY KEY (id),
    CONSTRAINT fk_contract_types_field_set_id FOREIGN KEY (field_set_id) REFERENCES field_sets (id) ON DELETE CASCADE,
    CONSTRAINT uq_contract_types_field_set_id_key UNIQUE (field_set_id, key),
    CONSTRAINT uq_contract_types_field_set_id_position UNIQUE (field_set_id, position),
    CONSTRAINT ck_contract_types_key CHECK (key ~ '^[a-z][a-z0-9_]*$')
);
-- At most one fallback type per field set.
CREATE UNIQUE INDEX uq_contract_types_fallback ON contract_types (field_set_id) WHERE is_fallback;

-- Fields a contract type expects, with the group they are listed under and their priority for that type.
-- Type and field belong to the same field set (enforced by the catalogue generator and the config API).
CREATE TABLE contract_type_fields (
    contract_type_id uuid    NOT NULL,
    field_id         uuid    NOT NULL,
    -- core, commercial, risk_liability, restrictive_covenants, ip_data, or specific (the type's own fields).
    field_group      text    NOT NULL,
    priority         text    NOT NULL,
    position         integer NOT NULL,
    CONSTRAINT pk_contract_type_fields PRIMARY KEY (contract_type_id, field_id),
    CONSTRAINT fk_contract_type_fields_contract_type_id FOREIGN KEY (contract_type_id) REFERENCES contract_types (id) ON DELETE CASCADE,
    CONSTRAINT fk_contract_type_fields_field_id FOREIGN KEY (field_id) REFERENCES fields (id) ON DELETE CASCADE,
    CONSTRAINT uq_contract_type_fields_contract_type_id_position UNIQUE (contract_type_id, position),
    CONSTRAINT ck_contract_type_fields_field_group CHECK (field_group ~ '^[a-z][a-z0-9_]*$'),
    CONSTRAINT ck_contract_type_fields_priority CHECK (priority IN ('P1', 'P2', 'P3'))
);
CREATE INDEX ix_contract_type_fields_field_id ON contract_type_fields (field_id);

-- A runnable recipe: which decomposition, index, fields, models, prompts and RAG configs a run uses.
CREATE TABLE pipeline_configs (
    id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
    name                    text        NOT NULL,
    description             text,
    decomposition_config_id uuid        NOT NULL,
    index_config_id         uuid        NOT NULL,
    field_set_id            uuid        NOT NULL,
    extraction_profile_id   uuid        NOT NULL,
    extraction_prompt_id    uuid        NOT NULL,
    judge_enabled           boolean     NOT NULL DEFAULT true,
    judge_profile_id        uuid,
    judge_prompt_id         uuid,
    -- Judge calls run concurrently with extraction.
    judge_parallel          boolean     NOT NULL DEFAULT false,
    -- Detect the contract type(s) first and extract only their fields; off: the fallback type's fields.
    classification_enabled        boolean      NOT NULL DEFAULT false,
    classification_profile_id     uuid,
    classification_prompt_id      uuid,
    -- The classifier reads the document's first pages (title, parties, recitals).
    classification_pages          integer      NOT NULL DEFAULT 3,
    -- A proposed type is used when its confidence reaches this; none reaching it means the fallback type.
    classification_min_confidence numeric(4, 3) NOT NULL DEFAULT 0.5,
    -- Lowest field priority extracted: P3 = every field, P1 = only direct financial, time or exit exposure.
    min_priority                  text         NOT NULL DEFAULT 'P3',
    -- field: one retrieval and LLM call per field. group: one per field group (Core, Commercial, ...), with
    -- evidence from all the group's queries; groups larger than group_max_fields are split.
    extraction_granularity        text         NOT NULL DEFAULT 'field',
    group_max_fields              integer      NOT NULL DEFAULT 8,
    is_default              boolean     NOT NULL DEFAULT false,
    created_at              timestamptz NOT NULL DEFAULT now(),
    updated_at              timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_pipeline_configs PRIMARY KEY (id),
    CONSTRAINT fk_pipeline_configs_decomposition_config_id FOREIGN KEY (decomposition_config_id) REFERENCES decomposition_configs (id),
    CONSTRAINT fk_pipeline_configs_index_config_id FOREIGN KEY (index_config_id) REFERENCES index_configs (id),
    CONSTRAINT fk_pipeline_configs_field_set_id FOREIGN KEY (field_set_id) REFERENCES field_sets (id),
    CONSTRAINT fk_pipeline_configs_extraction_profile_id FOREIGN KEY (extraction_profile_id) REFERENCES model_profiles (id),
    CONSTRAINT fk_pipeline_configs_extraction_prompt_id FOREIGN KEY (extraction_prompt_id) REFERENCES prompt_templates (id),
    CONSTRAINT fk_pipeline_configs_judge_profile_id FOREIGN KEY (judge_profile_id) REFERENCES model_profiles (id),
    CONSTRAINT fk_pipeline_configs_judge_prompt_id FOREIGN KEY (judge_prompt_id) REFERENCES prompt_templates (id),
    CONSTRAINT fk_pipeline_configs_classification_profile_id FOREIGN KEY (classification_profile_id) REFERENCES model_profiles (id),
    CONSTRAINT fk_pipeline_configs_classification_prompt_id FOREIGN KEY (classification_prompt_id) REFERENCES prompt_templates (id),
    CONSTRAINT uq_pipeline_configs_name UNIQUE (name),
    CONSTRAINT ck_pipeline_configs_judge CHECK (NOT judge_enabled OR (judge_profile_id IS NOT NULL AND judge_prompt_id IS NOT NULL)),
    CONSTRAINT ck_pipeline_configs_classification CHECK (
        NOT classification_enabled OR (classification_profile_id IS NOT NULL AND classification_prompt_id IS NOT NULL)),
    CONSTRAINT ck_pipeline_configs_classification_pages CHECK (classification_pages > 0),
    CONSTRAINT ck_pipeline_configs_classification_min_confidence CHECK (classification_min_confidence BETWEEN 0 AND 1),
    CONSTRAINT ck_pipeline_configs_min_priority CHECK (min_priority IN ('P1', 'P2', 'P3')),
    CONSTRAINT ck_pipeline_configs_extraction_granularity CHECK (extraction_granularity IN ('field', 'group')),
    CONSTRAINT ck_pipeline_configs_group_max_fields CHECK (group_max_fields > 0)
);
CREATE UNIQUE INDEX uq_pipeline_configs_default ON pipeline_configs (is_default) WHERE is_default;

-- RAG configs a pipeline runs, in priority order (position 1 = preferred answer).
CREATE TABLE pipeline_config_retrievals (
    pipeline_config_id  uuid    NOT NULL,
    retrieval_config_id uuid    NOT NULL,
    position            integer NOT NULL,
    CONSTRAINT pk_pipeline_config_retrievals PRIMARY KEY (pipeline_config_id, retrieval_config_id),
    CONSTRAINT fk_pipeline_config_retrievals_pipeline_config_id FOREIGN KEY (pipeline_config_id) REFERENCES pipeline_configs (id) ON DELETE CASCADE,
    CONSTRAINT fk_pipeline_config_retrievals_retrieval_config_id FOREIGN KEY (retrieval_config_id) REFERENCES retrieval_configs (id),
    CONSTRAINT uq_pipeline_config_retrievals_pipeline_config_id_position UNIQUE (pipeline_config_id, position)
);
CREATE INDEX ix_pipeline_config_retrievals_retrieval_config_id ON pipeline_config_retrievals (retrieval_config_id);

-- =====================================================================================================
-- 2. Documents & artifacts
-- =====================================================================================================

CREATE TABLE documents (
    id                uuid        NOT NULL DEFAULT gen_random_uuid(),
    code              text        NOT NULL DEFAULT next_document_code(),
    title             text,
    original_filename text        NOT NULL,
    mime_type         text        NOT NULL DEFAULT 'application/pdf',
    -- Detected at upload; picks the converter used by decomposition.
    format            text        NOT NULL DEFAULT 'pdf',
    sha256           char(64)    NOT NULL,
    size_bytes        bigint      NOT NULL,
    page_count        integer,
    -- Path of the stored source file, relative to the storage root.
    storage_path      text        NOT NULL,
    tags              text[]      NOT NULL DEFAULT '{}',
    metadata          jsonb       NOT NULL DEFAULT '{}',
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_documents PRIMARY KEY (id),
    CONSTRAINT uq_documents_code UNIQUE (code),
    -- The same file is stored once; uploading it again returns the existing document.
    CONSTRAINT uq_documents_sha256 UNIQUE (sha256),
    CONSTRAINT ck_documents_format CHECK (format IN ('pdf', 'image', 'html', 'txt', 'docx')),
    CONSTRAINT ck_documents_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_documents_size_bytes CHECK (size_bytes >= 0),
    CONSTRAINT ck_documents_page_count CHECK (page_count IS NULL OR page_count >= 0)
);
CREATE INDEX ix_documents_created_at ON documents (created_at DESC);
CREATE INDEX ix_documents_tags ON documents USING gin (tags);

-- One row per decomposition attempt; earlier decompositions are never overwritten.
CREATE TABLE decompositions (
    id                      uuid        NOT NULL DEFAULT gen_random_uuid(),
    document_id             uuid        NOT NULL,
    decomposition_config_id uuid        NOT NULL,
    config_snapshot         jsonb       NOT NULL DEFAULT '{}',
    -- What actually ran, e.g. 'pdf:pymupdf', 'image:ocr', 'html'.
    converter               text        NOT NULL,
    -- Folder with page JSON and images, relative to the storage root.
    storage_dir             text        NOT NULL,
    page_count              integer     NOT NULL,
    duration_ms             integer     NOT NULL,
    -- clock_timestamp(): several decompositions created in one transaction must still be ordered.
    created_at              timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_decompositions PRIMARY KEY (id),
    CONSTRAINT fk_decompositions_document_id FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT fk_decompositions_decomposition_config_id FOREIGN KEY (decomposition_config_id) REFERENCES decomposition_configs (id),
    CONSTRAINT ck_decompositions_counts CHECK (page_count >= 0 AND duration_ms >= 0)
);
CREATE INDEX ix_decompositions_document_id ON decompositions (document_id, created_at DESC);
CREATE INDEX ix_decompositions_decomposition_config_id ON decompositions (decomposition_config_id);

CREATE TABLE pages (
    id               uuid        NOT NULL DEFAULT gen_random_uuid(),
    decomposition_id uuid        NOT NULL,
    page_number      integer     NOT NULL,
    text             text        NOT NULL,
    text_format      text        NOT NULL,
    header           text,
    footer           text,
    width            real,
    height           real,
    metadata         jsonb       NOT NULL DEFAULT '{}',
    -- Full-text search over page text (debugging, evidence lookup).
    search           tsvector    GENERATED ALWAYS AS (to_tsvector('english', text)) STORED,
    CONSTRAINT pk_pages PRIMARY KEY (id),
    CONSTRAINT fk_pages_decomposition_id FOREIGN KEY (decomposition_id) REFERENCES decompositions (id) ON DELETE CASCADE,
    CONSTRAINT uq_pages_decomposition_id_page_number UNIQUE (decomposition_id, page_number),
    CONSTRAINT ck_pages_page_number CHECK (page_number > 0),
    CONSTRAINT ck_pages_text_format CHECK (text_format IN ('md', 'html'))
);
CREATE INDEX ix_pages_search ON pages USING gin (search);

CREATE TABLE page_images (
    id               uuid        NOT NULL DEFAULT gen_random_uuid(),
    page_id          uuid        NOT NULL,
    file_name        text        NOT NULL,
    storage_path     text        NOT NULL,
    width            integer,
    height           integer,
    caption          text,
    caption_model_id uuid,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_page_images PRIMARY KEY (id),
    CONSTRAINT fk_page_images_page_id FOREIGN KEY (page_id) REFERENCES pages (id) ON DELETE CASCADE,
    CONSTRAINT fk_page_images_caption_model_id FOREIGN KEY (caption_model_id) REFERENCES llm_models (id),
    CONSTRAINT uq_page_images_page_id_file_name UNIQUE (page_id, file_name)
);

-- One vector collection per decomposition and index config, reused by later runs.
CREATE TABLE vector_indexes (
    id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
    decomposition_id   uuid        NOT NULL,
    index_config_id    uuid        NOT NULL,
    vector_store       text        NOT NULL,
    collection_name    text        NOT NULL,
    embedding_model_id uuid        NOT NULL,
    dimension          integer     NOT NULL,
    chunk_count        integer     NOT NULL DEFAULT 0,
    status             text        NOT NULL DEFAULT 'building',
    error              text,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_vector_indexes PRIMARY KEY (id),
    CONSTRAINT fk_vector_indexes_decomposition_id FOREIGN KEY (decomposition_id) REFERENCES decompositions (id) ON DELETE CASCADE,
    CONSTRAINT fk_vector_indexes_index_config_id FOREIGN KEY (index_config_id) REFERENCES index_configs (id),
    CONSTRAINT fk_vector_indexes_embedding_model_id FOREIGN KEY (embedding_model_id) REFERENCES llm_models (id),
    CONSTRAINT uq_vector_indexes_collection_name UNIQUE (collection_name),
    CONSTRAINT uq_vector_indexes_decomposition_id_index_config_id UNIQUE (decomposition_id, index_config_id),
    CONSTRAINT ck_vector_indexes_vector_store CHECK (vector_store IN ('qdrant', 'memory')),
    CONSTRAINT ck_vector_indexes_status CHECK (status IN ('building', 'ready', 'failed')),
    CONSTRAINT ck_vector_indexes_counts CHECK (dimension > 0 AND chunk_count >= 0)
);
CREATE INDEX ix_vector_indexes_index_config_id ON vector_indexes (index_config_id);

-- Chunk text kept for provenance; chunks.id is the point id in the vector store.
CREATE TABLE chunks (
    id              uuid    NOT NULL DEFAULT gen_random_uuid(),
    vector_index_id uuid    NOT NULL,
    chunk_index     integer NOT NULL,
    page_start      integer NOT NULL,
    page_end        integer NOT NULL,
    char_start      integer,
    char_end        integer,
    text            text    NOT NULL,
    -- Embedded and keyword-indexed instead of text: Markdown removed, tables as rows, section in front.
    search_text     text    NOT NULL,
    -- The chunk's section and the headings inside it, one per line (weighted up in keyword search).
    headings        text    NOT NULL DEFAULT '',
    CONSTRAINT pk_chunks PRIMARY KEY (id),
    CONSTRAINT fk_chunks_vector_index_id FOREIGN KEY (vector_index_id) REFERENCES vector_indexes (id) ON DELETE CASCADE,
    CONSTRAINT uq_chunks_vector_index_id_chunk_index UNIQUE (vector_index_id, chunk_index),
    CONSTRAINT ck_chunks_pages CHECK (page_start > 0 AND page_end >= page_start),
    CONSTRAINT ck_chunks_chars CHECK (char_start IS NULL OR char_end IS NULL OR char_end >= char_start)
);

-- =====================================================================================================
-- 3. Runs & results
-- =====================================================================================================

-- Groups runs that belong to one research question.
CREATE TABLE experiments (
    id          uuid        NOT NULL DEFAULT gen_random_uuid(),
    name        text        NOT NULL,
    description text,
    hypothesis  text,
    -- What the experiment runs (pipelines, repeats, run options, and the documents with their fields), fixed
    -- when it is created; see experiments.py.
    design      jsonb       NOT NULL DEFAULT '{}',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_experiments PRIMARY KEY (id),
    CONSTRAINT uq_experiments_name UNIQUE (name)
);

-- A unit of work for the worker; this table is also the job queue (claimed with FOR UPDATE SKIP LOCKED).
CREATE TABLE runs (
    id                 uuid        NOT NULL DEFAULT gen_random_uuid(),
    document_id        uuid        NOT NULL,
    pipeline_config_id uuid        NOT NULL,
    experiment_id      uuid,
    kind               text        NOT NULL DEFAULT 'full',
    state              text        NOT NULL DEFAULT 'queued',
    stage              text,
    -- Set as stages complete (or chosen up front for an extract-only run).
    decomposition_id   uuid,
    vector_index_id    uuid,
    progress_done      integer     NOT NULL DEFAULT 0,
    progress_total     integer     NOT NULL DEFAULT 0,
    -- Per-run overrides chosen by the caller.
    options            jsonb       NOT NULL DEFAULT '{}',
    -- Fully resolved configuration (pipeline + models + prompts + RAG configs + fields) used by this run.
    config_snapshot    jsonb       NOT NULL DEFAULT '{}',
    error              text,
    cancel_requested   boolean     NOT NULL DEFAULT false,
    attempts           integer     NOT NULL DEFAULT 0,
    max_attempts       integer     NOT NULL DEFAULT 1,
    worker_id          text,
    heartbeat_at       timestamptz,
    queued_at          timestamptz NOT NULL DEFAULT now(),
    started_at         timestamptz,
    finished_at        timestamptz,
    CONSTRAINT pk_runs PRIMARY KEY (id),
    CONSTRAINT fk_runs_document_id FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT fk_runs_pipeline_config_id FOREIGN KEY (pipeline_config_id) REFERENCES pipeline_configs (id),
    CONSTRAINT fk_runs_experiment_id FOREIGN KEY (experiment_id) REFERENCES experiments (id) ON DELETE SET NULL,
    CONSTRAINT fk_runs_decomposition_id FOREIGN KEY (decomposition_id) REFERENCES decompositions (id) ON DELETE SET NULL,
    CONSTRAINT fk_runs_vector_index_id FOREIGN KEY (vector_index_id) REFERENCES vector_indexes (id) ON DELETE SET NULL,
    CONSTRAINT ck_runs_kind CHECK (kind IN ('full', 'decompose', 'extract')),
    CONSTRAINT ck_runs_state CHECK (state IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')),
    CONSTRAINT ck_runs_stage CHECK (stage IS NULL OR stage IN ('decomposing', 'indexing', 'classifying', 'extracting')),
    CONSTRAINT ck_runs_progress CHECK (progress_done >= 0 AND progress_done <= progress_total),
    CONSTRAINT ck_runs_attempts CHECK (attempts >= 0 AND max_attempts > 0 AND attempts <= max_attempts),
    CONSTRAINT ck_runs_started CHECK (state <> 'running' OR started_at IS NOT NULL),
    CONSTRAINT ck_runs_finished CHECK ((state IN ('succeeded', 'failed', 'cancelled')) = (finished_at IS NOT NULL))
);
-- At most one queued or running run per document.
CREATE UNIQUE INDEX uq_runs_active_document ON runs (document_id) WHERE state IN ('queued', 'running');
-- Worker claim: oldest queued run first.
CREATE INDEX ix_runs_queued ON runs (queued_at) WHERE state = 'queued';
-- Stale-run recovery: running runs by heartbeat.
CREATE INDEX ix_runs_running_heartbeat_at ON runs (heartbeat_at) WHERE state = 'running';
CREATE INDEX ix_runs_document_id_queued_at ON runs (document_id, queued_at DESC);
CREATE INDEX ix_runs_pipeline_config_id ON runs (pipeline_config_id);
CREATE INDEX ix_runs_experiment_id ON runs (experiment_id) WHERE experiment_id IS NOT NULL;

-- Timeline and log of a run.
CREATE TABLE run_events (
    id         bigint      GENERATED ALWAYS AS IDENTITY,
    run_id     uuid        NOT NULL,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    level      text        NOT NULL DEFAULT 'info',
    stage      text,
    message    text        NOT NULL,
    data       jsonb       NOT NULL DEFAULT '{}',
    CONSTRAINT pk_run_events PRIMARY KEY (id),
    CONSTRAINT fk_run_events_run_id FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE,
    CONSTRAINT ck_run_events_level CHECK (level IN ('debug', 'info', 'warning', 'error'))
);
CREATE INDEX ix_run_events_run_id_id ON run_events (run_id, id);

-- One extraction outcome per run x RAG config x field.
CREATE TABLE field_results (
    id                  uuid        NOT NULL DEFAULT gen_random_uuid(),
    run_id              uuid        NOT NULL,
    field_id            uuid        NOT NULL,
    retrieval_config_id uuid        NOT NULL,
    status              text        NOT NULL,
    value               jsonb,
    raw_answer          text,
    error               text,
    extraction_ms       integer,
    -- clock_timestamp(), not now(): rows written in one transaction must still be ordered.
    created_at          timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_field_results PRIMARY KEY (id),
    CONSTRAINT fk_field_results_run_id FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_field_results_field_id FOREIGN KEY (field_id) REFERENCES fields (id),
    CONSTRAINT fk_field_results_retrieval_config_id FOREIGN KEY (retrieval_config_id) REFERENCES retrieval_configs (id),
    CONSTRAINT uq_field_results_run_id_retrieval_config_id_field_id UNIQUE (run_id, retrieval_config_id, field_id),
    CONSTRAINT ck_field_results_status CHECK (status IN ('extracted', 'not_found', 'error')),
    CONSTRAINT ck_field_results_value CHECK (status <> 'extracted' OR value IS NOT NULL),
    CONSTRAINT ck_field_results_error CHECK (status <> 'error' OR error IS NOT NULL),
    CONSTRAINT ck_field_results_extraction_ms CHECK (extraction_ms IS NULL OR extraction_ms >= 0)
);
CREATE INDEX ix_field_results_field_id ON field_results (field_id);
CREATE INDEX ix_field_results_retrieval_config_id ON field_results (retrieval_config_id);

-- Chunks retrieved as evidence for a field result.
CREATE TABLE retrieval_hits (
    field_result_id uuid             NOT NULL,
    rank            integer          NOT NULL,
    chunk_id        uuid             NOT NULL,
    -- Best dense (cosine) score; NULL for a chunk found only by keyword or as an anchor.
    score           double precision,
    -- Expansion query that found the chunk (NULL without query expansion).
    matched_query   text,
    -- Best keyword (BM25) score; NULL for a chunk keyword search did not find.
    keyword_score   double precision,
    -- Cross-encoder score when the RAG config reranks; NULL otherwise and for anchor chunks.
    rerank_score    double precision,
    source          text             NOT NULL DEFAULT 'dense',
    CONSTRAINT pk_retrieval_hits PRIMARY KEY (field_result_id, rank),
    CONSTRAINT fk_retrieval_hits_field_result_id FOREIGN KEY (field_result_id) REFERENCES field_results (id) ON DELETE CASCADE,
    CONSTRAINT fk_retrieval_hits_chunk_id FOREIGN KEY (chunk_id) REFERENCES chunks (id),
    CONSTRAINT ck_retrieval_hits_rank CHECK (rank > 0),
    CONSTRAINT ck_retrieval_hits_source CHECK (source IN ('dense', 'keyword', 'both', 'anchor'))
);
CREATE INDEX ix_retrieval_hits_chunk_id ON retrieval_hits (chunk_id);

-- Every call to an LLM: full prompt, response, usage and cost.
CREATE TABLE llm_calls (
    id                uuid           NOT NULL DEFAULT gen_random_uuid(),
    run_id            uuid,
    field_result_id   uuid,
    purpose           text           NOT NULL,
    model_profile_id  uuid,
    -- Copied at call time so the record survives later config edits.
    provider_key      text           NOT NULL,
    model_name        text           NOT NULL,
    params            jsonb          NOT NULL DEFAULT '{}',
    system_prompt     text,
    user_prompt       text,
    response          text,
    status            text           NOT NULL,
    error             text,
    prompt_tokens     integer,
    completion_tokens integer,
    latency_ms        integer,
    cost_usd          numeric(12, 6),
    created_at        timestamptz    NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_llm_calls PRIMARY KEY (id),
    CONSTRAINT fk_llm_calls_run_id FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_llm_calls_field_result_id FOREIGN KEY (field_result_id) REFERENCES field_results (id) ON DELETE CASCADE,
    CONSTRAINT fk_llm_calls_model_profile_id FOREIGN KEY (model_profile_id) REFERENCES model_profiles (id) ON DELETE SET NULL,
    CONSTRAINT ck_llm_calls_purpose CHECK (purpose IN ('extraction', 'judge', 'classification', 'caption', 'embedding')),
    CONSTRAINT ck_llm_calls_status CHECK (status IN ('ok', 'error', 'timeout')),
    CONSTRAINT ck_llm_calls_usage CHECK (
        (prompt_tokens IS NULL OR prompt_tokens >= 0) AND (completion_tokens IS NULL OR completion_tokens >= 0)
        AND (latency_ms IS NULL OR latency_ms >= 0) AND (cost_usd IS NULL OR cost_usd >= 0))
);
CREATE INDEX ix_llm_calls_run_id ON llm_calls (run_id, created_at);
CREATE INDEX ix_llm_calls_field_result_id ON llm_calls (field_result_id);

-- Field results produced by one LLM call that answered several fields (group extraction). Such a call
-- has no llm_calls.field_result_id.
CREATE TABLE llm_call_field_results (
    llm_call_id     uuid NOT NULL,
    field_result_id uuid NOT NULL,
    CONSTRAINT pk_llm_call_field_results PRIMARY KEY (llm_call_id, field_result_id),
    CONSTRAINT fk_llm_call_field_results_llm_call_id FOREIGN KEY (llm_call_id) REFERENCES llm_calls (id) ON DELETE CASCADE,
    CONSTRAINT fk_llm_call_field_results_field_result_id FOREIGN KEY (field_result_id) REFERENCES field_results (id) ON DELETE CASCADE
);
CREATE INDEX ix_llm_call_field_results_field_result_id ON llm_call_field_results (field_result_id);

-- LLM-judge verdicts; a field result can be judged again (e.g. by another model), the latest counts.
CREATE TABLE judgements (
    id               uuid        NOT NULL DEFAULT gen_random_uuid(),
    field_result_id  uuid        NOT NULL,
    model_profile_id uuid,
    verdict          text        NOT NULL,
    issue            text,
    explanation      text,
    llm_call_id      uuid,
    created_at       timestamptz NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_judgements PRIMARY KEY (id),
    CONSTRAINT fk_judgements_field_result_id FOREIGN KEY (field_result_id) REFERENCES field_results (id) ON DELETE CASCADE,
    CONSTRAINT fk_judgements_model_profile_id FOREIGN KEY (model_profile_id) REFERENCES model_profiles (id) ON DELETE SET NULL,
    CONSTRAINT fk_judgements_llm_call_id FOREIGN KEY (llm_call_id) REFERENCES llm_calls (id) ON DELETE SET NULL,
    CONSTRAINT ck_judgements_verdict CHECK (verdict IN ('PASS', 'FAIL', 'ERROR', 'SKIPPED')),
    CONSTRAINT ck_judgements_issue CHECK (issue IS NULL OR issue IN ('NONE', 'HALLUCINATION', 'INCOMPLETE', 'NO_CONTEXT')),
    CONSTRAINT ck_judgements_pass_issue CHECK (verdict <> 'PASS' OR issue IS NULL OR issue = 'NONE')
);
CREATE INDEX ix_judgements_field_result_id_created_at ON judgements (field_result_id, created_at DESC);

-- Contract types considered for a run. The selected ones decide which fields the run extracts.
--   classifier: proposed by the classification LLM (selected when confidence >= the pipeline's minimum)
--   override:   chosen in the run options (the classifier is not called)
--   fallback:   the fallback type, used when nothing else was selected
CREATE TABLE run_classifications (
    run_id           uuid          NOT NULL,
    contract_type_id uuid          NOT NULL,
    source           text          NOT NULL,
    selected         boolean       NOT NULL,
    confidence       numeric(4, 3),
    -- Quote or reason the classifier gave.
    evidence         text,
    llm_call_id      uuid,
    created_at       timestamptz   NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT pk_run_classifications PRIMARY KEY (run_id, contract_type_id),
    CONSTRAINT fk_run_classifications_run_id FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE,
    CONSTRAINT fk_run_classifications_contract_type_id FOREIGN KEY (contract_type_id) REFERENCES contract_types (id),
    CONSTRAINT fk_run_classifications_llm_call_id FOREIGN KEY (llm_call_id) REFERENCES llm_calls (id) ON DELETE SET NULL,
    CONSTRAINT ck_run_classifications_source CHECK (source IN ('classifier', 'override', 'fallback')),
    CONSTRAINT ck_run_classifications_confidence CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1)
);
CREATE INDEX ix_run_classifications_contract_type_id ON run_classifications (contract_type_id);

-- =====================================================================================================
-- 4. Evaluation
-- =====================================================================================================

-- Human-labelled expected values, for measuring extraction accuracy.
CREATE TABLE ground_truth (
    id             uuid        NOT NULL DEFAULT gen_random_uuid(),
    document_id    uuid        NOT NULL,
    field_id       uuid        NOT NULL,
    expected_value jsonb       NOT NULL,
    notes          text,
    created_by     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_ground_truth PRIMARY KEY (id),
    CONSTRAINT fk_ground_truth_document_id FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT fk_ground_truth_field_id FOREIGN KEY (field_id) REFERENCES fields (id) ON DELETE CASCADE,
    CONSTRAINT uq_ground_truth_document_id_field_id UNIQUE (document_id, field_id)
);
CREATE INDEX ix_ground_truth_field_id ON ground_truth (field_id);

-- Human-labelled contract types of a document, for measuring classification.
CREATE TABLE document_contract_types (
    document_id      uuid        NOT NULL,
    contract_type_id uuid        NOT NULL,
    created_at       timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT pk_document_contract_types PRIMARY KEY (document_id, contract_type_id),
    CONSTRAINT fk_document_contract_types_document_id FOREIGN KEY (document_id) REFERENCES documents (id) ON DELETE CASCADE,
    CONSTRAINT fk_document_contract_types_contract_type_id FOREIGN KEY (contract_type_id) REFERENCES contract_types (id) ON DELETE CASCADE
);
CREATE INDEX ix_document_contract_types_contract_type_id ON document_contract_types (contract_type_id);

-- Best value per run and field: a PASS from the highest-priority RAG config, otherwise the first
-- extracted value in priority order, otherwise the first outcome. Every field with an outcome appears once.
-- Priority comes from the run's own snapshot, so later pipeline edits never change a past run's best values.
CREATE VIEW v_best_values AS
SELECT DISTINCT ON (fr.run_id, fr.field_id)
    fr.run_id,
    r.document_id,
    fr.field_id,
    f.key                AS field_key,
    f.label              AS field_label,
    fr.id                AS field_result_id,
    rc.name              AS retrieval_config,
    fr.status,
    fr.value,
    j.verdict,
    j.issue,
    j.explanation
FROM field_results fr
JOIN runs r                ON r.id = fr.run_id
JOIN fields f              ON f.id = fr.field_id
JOIN retrieval_configs rc  ON rc.id = fr.retrieval_config_id
LEFT JOIN LATERAL (
    SELECT e.position
    FROM jsonb_array_elements(r.config_snapshot -> 'retrievals') WITH ORDINALITY AS e(retrieval, position)
    WHERE (e.retrieval ->> 'id')::uuid = fr.retrieval_config_id
    LIMIT 1
) sp ON true
LEFT JOIN LATERAL (
    SELECT jd.verdict, jd.issue, jd.explanation
    FROM judgements jd
    WHERE jd.field_result_id = fr.id
    ORDER BY jd.created_at DESC
    LIMIT 1
) j ON true
ORDER BY fr.run_id, fr.field_id,
         (j.verdict = 'PASS') DESC NULLS LAST,
         (fr.status = 'extracted') DESC,
         sp.position NULLS LAST,
         fr.created_at;

-- Best values next to the ground truth. exact_match compares trimmed, case-insensitive text, and objects and
-- lists as JSON (key order ignored, and keys whose value is null or "" left out); NULL when no label exists, false for an error outcome,
-- which must never count as correct. A label of "" means "not in this contract" and matches a not_found outcome.
-- Partial credit for objects and lists is computed by the API (evaluation.py).
CREATE VIEW v_run_evaluation AS
SELECT
    b.run_id,
    b.document_id,
    b.field_id,
    b.field_key,
    b.retrieval_config,
    b.value          AS extracted_value,
    gt.expected_value,
    b.verdict,
    CASE
        WHEN gt.id IS NULL THEN NULL
        WHEN b.status = 'error' THEN false
        WHEN jsonb_typeof(gt.expected_value) IN ('object', 'array')
            THEN coalesce(jsonb_strip_empty(b.value) = jsonb_strip_empty(gt.expected_value), false)
        ELSE lower(btrim(coalesce(b.value #>> '{}', ''))) = lower(btrim(coalesce(gt.expected_value #>> '{}', '')))
    END              AS exact_match
FROM v_best_values b
LEFT JOIN ground_truth gt ON gt.document_id = b.document_id AND gt.field_id = b.field_id;

-- updated_at maintenance
CREATE TRIGGER trg_llm_providers_updated_at         BEFORE UPDATE ON llm_providers         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_llm_models_updated_at            BEFORE UPDATE ON llm_models            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_model_profiles_updated_at        BEFORE UPDATE ON model_profiles        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_decomposition_configs_updated_at BEFORE UPDATE ON decomposition_configs FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_index_configs_updated_at         BEFORE UPDATE ON index_configs         FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_retrieval_configs_updated_at     BEFORE UPDATE ON retrieval_configs     FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_field_sets_updated_at            BEFORE UPDATE ON field_sets            FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_fields_updated_at                BEFORE UPDATE ON fields                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_contract_types_updated_at        BEFORE UPDATE ON contract_types        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_pipeline_configs_updated_at      BEFORE UPDATE ON pipeline_configs      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_documents_updated_at             BEFORE UPDATE ON documents             FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_vector_indexes_updated_at        BEFORE UPDATE ON vector_indexes        FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_experiments_updated_at           BEFORE UPDATE ON experiments           FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_ground_truth_updated_at          BEFORE UPDATE ON ground_truth          FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMIT;
