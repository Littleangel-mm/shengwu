-- 通用科研文献智能解析与机器学习系统
-- PostgreSQL 15+ 初始数据库结构
-- Version: 1.0.0
-- Date: 2026-07-18
--
-- Design goals:
--   1. Domain-neutral: no industry-specific fields are hard-coded.
--   2. Traceable: every formal value can be linked to source evidence.
--   3. Versioned: field schemas, datasets, models, reports and rules are versioned.
--   4. Extensible: parsers, LLM providers, templates and model algorithms are pluggable.
--   5. Safe: original files/evidence are separated from normalized and ML values.
--
-- Run this file with a database owner account. Application roles/grants should be
-- created by the deployment environment because role names differ per installation.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- The application uses its own database and keeps objects in public so common
-- database management tools display the tables without additional schema filters.
SET search_path TO public;

-- -----------------------------------------------------------------------------
-- Shared functions
-- -----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_row_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'Rows in %.% are append-only', TG_TABLE_SCHEMA, TG_TABLE_NAME;
END;
$$;

-- -----------------------------------------------------------------------------
-- Schema metadata
-- -----------------------------------------------------------------------------

CREATE TABLE schema_revisions (
    revision                 varchar(64) PRIMARY KEY,
    description              text NOT NULL,
    applied_at               timestamptz NOT NULL DEFAULT now()
);

INSERT INTO schema_revisions (revision, description)
VALUES ('001_initial_schema', 'Initial extensible schema for the research document platform')
ON CONFLICT (revision) DO NOTHING;

-- -----------------------------------------------------------------------------
-- Identity, organizations and projects
-- -----------------------------------------------------------------------------

CREATE TABLE app_users (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email                    varchar(320) NOT NULL,
    display_name             varchar(200) NOT NULL,
    password_hash            text,
    auth_provider            varchar(50) NOT NULL DEFAULT 'local',
    external_subject         varchar(255),
    locale                   varchar(20) NOT NULL DEFAULT 'zh-CN',
    timezone                 varchar(64) NOT NULL DEFAULT 'Asia/Shanghai',
    status                   varchar(32) NOT NULL DEFAULT 'active',
    preferences              jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_login_at            timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    deleted_at               timestamptz,
    CONSTRAINT uq_app_users_email UNIQUE (email),
    CONSTRAINT uq_app_users_external_subject UNIQUE (auth_provider, external_subject)
);

CREATE TABLE auth_login_attempts (
    key_hash                 char(64) PRIMARY KEY,
    failed_count             integer NOT NULL DEFAULT 0 CHECK (failed_count >= 0),
    window_started_at        timestamptz NOT NULL DEFAULT now(),
    blocked_until            timestamptz,
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_auth_login_attempts_key CHECK (key_hash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_auth_login_attempts_blocked_until
    ON auth_login_attempts(blocked_until)
    WHERE blocked_until IS NOT NULL;

CREATE TABLE organizations (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name                     varchar(200) NOT NULL,
    slug                     varchar(100) NOT NULL,
    status                   varchar(32) NOT NULL DEFAULT 'active',
    settings                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    deleted_at               timestamptz,
    CONSTRAINT uq_organizations_slug UNIQUE (slug)
);

CREATE TABLE organization_members (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id                  uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    role                     varchar(32) NOT NULL DEFAULT 'member',
    status                   varchar(32) NOT NULL DEFAULT 'active',
    joined_at                timestamptz NOT NULL DEFAULT now(),
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_organization_members UNIQUE (organization_id, user_id)
);

CREATE TABLE projects (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    name                     varchar(240) NOT NULL,
    slug                     varchar(120) NOT NULL,
    description              text,
    research_domain          varchar(200),
    default_language         varchar(20) NOT NULL DEFAULT 'zh-CN',
    status                   varchar(32) NOT NULL DEFAULT 'active',
    settings                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    archived_at              timestamptz,
    deleted_at               timestamptz,
    CONSTRAINT uq_projects_slug UNIQUE (organization_id, slug)
);

CREATE TABLE project_members (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    user_id                  uuid NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    role                     varchar(32) NOT NULL DEFAULT 'viewer',
    permissions              jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_project_members UNIQUE (project_id, user_id)
);

-- A template is initialization data only. Projects copy and then own their configuration.
CREATE TABLE configuration_templates (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid REFERENCES organizations(id) ON DELETE CASCADE,
    template_type            varchar(50) NOT NULL,
    name                     varchar(200) NOT NULL,
    code                     varchar(100) NOT NULL,
    version                  integer NOT NULL DEFAULT 1 CHECK (version > 0),
    description              text,
    definition               jsonb NOT NULL,
    is_system                boolean NOT NULL DEFAULT false,
    is_active                boolean NOT NULL DEFAULT true,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_configuration_templates_scope
    ON configuration_templates (COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid), template_type, code, version);

-- -----------------------------------------------------------------------------
-- Units and deterministic conversion rules
-- -----------------------------------------------------------------------------

CREATE TABLE units (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    code                     varchar(80) NOT NULL,
    symbol                   varchar(80) NOT NULL,
    name                     varchar(160) NOT NULL,
    dimension                varchar(100) NOT NULL,
    system                   varchar(50),
    aliases                  jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_active                boolean NOT NULL DEFAULT true,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_units_code UNIQUE (code)
);

CREATE TABLE unit_conversion_rules (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid REFERENCES organizations(id) ON DELETE CASCADE,
    source_unit_id           uuid NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    target_unit_id           uuid NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    version                  integer NOT NULL DEFAULT 1 CHECK (version > 0),
    rule_name                varchar(200) NOT NULL,
    multiplier               numeric,
    offset_value             numeric,
    formula_expression       text,
    context_requirements     jsonb NOT NULL DEFAULT '{}'::jsonb,
    requires_confirmation    boolean NOT NULL DEFAULT false,
    source_reference         text,
    is_active                boolean NOT NULL DEFAULT true,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_unit_conversion_distinct CHECK (source_unit_id <> target_unit_id),
    CONSTRAINT ck_unit_conversion_method CHECK (
        (multiplier IS NOT NULL) OR (formula_expression IS NOT NULL)
    )
);

CREATE UNIQUE INDEX uq_unit_conversion_rule_scope
    ON unit_conversion_rules (
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        source_unit_id,
        target_unit_id,
        version
    );

-- -----------------------------------------------------------------------------
-- Object storage and logical documents
-- -----------------------------------------------------------------------------

CREATE TABLE stored_files (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id               uuid REFERENCES projects(id) ON DELETE CASCADE,
    storage_provider         varchar(32) NOT NULL DEFAULT 'local',
    storage_bucket           varchar(200),
    storage_key              text NOT NULL,
    original_name            text NOT NULL,
    safe_name                text NOT NULL,
    extension                varchar(32),
    media_type               varchar(160),
    byte_size                bigint NOT NULL CHECK (byte_size >= 0),
    sha256                   char(64) NOT NULL,
    purpose                  varchar(50) NOT NULL DEFAULT 'upload',
    security_status          varchar(32) NOT NULL DEFAULT 'pending',
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    deleted_at               timestamptz,
    CONSTRAINT uq_stored_files_key UNIQUE (storage_provider, storage_key),
    CONSTRAINT ck_stored_files_sha256 CHECK (sha256 ~ '^[0-9a-f]{64}$')
);

CREATE INDEX ix_stored_files_project ON stored_files(project_id, created_at DESC);
CREATE INDEX ix_stored_files_hash ON stored_files(organization_id, sha256);

CREATE TABLE documents (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_type            varchar(50) NOT NULL DEFAULT 'paper',
    title                    text,
    authors                  jsonb NOT NULL DEFAULT '[]'::jsonb,
    publication_year         integer,
    publication_date         date,
    publication_name         text,
    doi                      varchar(255),
    external_identifiers     jsonb NOT NULL DEFAULT '{}'::jsonb,
    language                 varchar(20),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    status                   varchar(32) NOT NULL DEFAULT 'active',
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    deleted_at               timestamptz
);

CREATE INDEX ix_documents_project ON documents(project_id, created_at DESC);
CREATE INDEX ix_documents_title_trgm ON documents USING gin (title gin_trgm_ops);
CREATE INDEX ix_documents_doi ON documents(doi) WHERE doi IS NOT NULL;

CREATE TABLE document_versions (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id              uuid NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    version_no               integer NOT NULL CHECK (version_no > 0),
    source_file_id           uuid NOT NULL REFERENCES stored_files(id) ON DELETE RESTRICT,
    source_kind              varchar(32) NOT NULL DEFAULT 'upload',
    parser_name              varchar(100),
    parser_version           varchar(100),
    detected_language        varchar(20),
    page_count               integer CHECK (page_count IS NULL OR page_count >= 0),
    parse_status             varchar(32) NOT NULL DEFAULT 'pending',
    parse_quality            numeric(5,4) CHECK (parse_quality IS NULL OR parse_quality BETWEEN 0 AND 1),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz,
    CONSTRAINT uq_document_versions UNIQUE (document_id, version_no),
    CONSTRAINT uq_document_source_file UNIQUE (document_id, source_file_id)
);

CREATE INDEX ix_document_versions_status ON document_versions(parse_status, created_at);

CREATE TABLE document_pages (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_no                  integer NOT NULL CHECK (page_no > 0),
    width                    numeric,
    height                   numeric,
    rotation                 smallint NOT NULL DEFAULT 0,
    text_content             text,
    text_source              varchar(32),
    ocr_confidence           numeric(5,4) CHECK (ocr_confidence IS NULL OR ocr_confidence BETWEEN 0 AND 1),
    rendered_image_file_id   uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_pages UNIQUE (document_version_id, page_no)
);

CREATE INDEX ix_document_pages_version ON document_pages(document_version_id, page_no);

CREATE TABLE document_blocks (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    parent_block_id          uuid REFERENCES document_blocks(id) ON DELETE CASCADE,
    block_type               varchar(50) NOT NULL,
    sequence_no              integer NOT NULL CHECK (sequence_no >= 0),
    section_path             jsonb NOT NULL DEFAULT '[]'::jsonb,
    content_text             text,
    bbox                     jsonb,
    style                    jsonb NOT NULL DEFAULT '{}'::jsonb,
    parser_payload           jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    search_vector            tsvector GENERATED ALWAYS AS (
        to_tsvector('simple', COALESCE(content_text, ''))
    ) STORED,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_blocks_sequence UNIQUE (document_version_id, page_id, sequence_no)
);

CREATE INDEX ix_document_blocks_page ON document_blocks(page_id, sequence_no);
CREATE INDEX ix_document_blocks_type ON document_blocks(document_version_id, block_type);
CREATE INDEX ix_document_blocks_search ON document_blocks USING gin(search_vector);
CREATE INDEX ix_document_blocks_trgm ON document_blocks USING gin(content_text gin_trgm_ops);

CREATE TABLE document_tables (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    source_block_id          uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    table_no                 varchar(100),
    title                    text,
    caption                  text,
    row_count                integer CHECK (row_count IS NULL OR row_count >= 0),
    column_count             integer CHECK (column_count IS NULL OR column_count >= 0),
    bbox                     jsonb,
    structured_data          jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_document_tables_version ON document_tables(document_version_id, page_id);

CREATE TABLE document_table_cells (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    table_id                 uuid NOT NULL REFERENCES document_tables(id) ON DELETE CASCADE,
    row_index                integer NOT NULL CHECK (row_index >= 0),
    column_index             integer NOT NULL CHECK (column_index >= 0),
    row_span                 integer NOT NULL DEFAULT 1 CHECK (row_span > 0),
    column_span              integer NOT NULL DEFAULT 1 CHECK (column_span > 0),
    cell_role                varchar(32),
    raw_text                 text,
    normalized_text          text,
    bbox                     jsonb,
    style                    jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_table_cells UNIQUE (table_id, row_index, column_index)
);

CREATE INDEX ix_document_table_cells_table ON document_table_cells(table_id, row_index, column_index);
CREATE INDEX ix_document_table_cells_trgm ON document_table_cells USING gin(raw_text gin_trgm_ops);

CREATE TABLE document_figures (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    source_block_id          uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    figure_no                varchar(100),
    title                    text,
    caption                  text,
    figure_type              varchar(50),
    bbox                     jsonb,
    image_file_id            uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    axis_metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,
    legend_metadata          jsonb NOT NULL DEFAULT '{}'::jsonb,
    extracted_labels         jsonb NOT NULL DEFAULT '[]'::jsonb,
    semantic_summary         text,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_document_figures_version ON document_figures(document_version_id, page_id);

CREATE TABLE document_translations (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    source_block_id          uuid NOT NULL REFERENCES document_blocks(id) ON DELETE CASCADE,
    source_language          varchar(20),
    target_language          varchar(20) NOT NULL,
    translated_text          text NOT NULL,
    provider                 varchar(100) NOT NULL,
    model_name               varchar(160),
    prompt_version           varchar(100),
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_document_translations
    ON document_translations(source_block_id, target_language, provider, COALESCE(model_name, ''));

-- Embeddings use a portable float array. A later migration may move this to pgvector.
CREATE TABLE document_embeddings (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    source_block_id          uuid NOT NULL REFERENCES document_blocks(id) ON DELETE CASCADE,
    provider                 varchar(100) NOT NULL,
    model_name               varchar(160) NOT NULL,
    dimensions               integer NOT NULL CHECK (dimensions > 0),
    embedding                double precision[],
    external_vector_id       text,
    content_sha256           char(64) NOT NULL,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_document_embeddings UNIQUE (source_block_id, provider, model_name),
    CONSTRAINT ck_document_embedding_location CHECK (
        embedding IS NOT NULL OR external_vector_id IS NOT NULL
    ),
    CONSTRAINT ck_document_embedding_dimensions CHECK (
        embedding IS NULL OR array_length(embedding, 1) = dimensions
    )
);

-- -----------------------------------------------------------------------------
-- Asynchronous jobs and artifacts
-- -----------------------------------------------------------------------------

CREATE TABLE processing_jobs (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    document_version_id      uuid REFERENCES document_versions(id) ON DELETE CASCADE,
    parent_job_id            uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    job_type                 varchar(64) NOT NULL,
    status                   varchar(32) NOT NULL DEFAULT 'queued',
    priority                 smallint NOT NULL DEFAULT 0,
    progress_percent         numeric(5,2) NOT NULL DEFAULT 0 CHECK (progress_percent BETWEEN 0 AND 100),
    current_stage            varchar(100),
    idempotency_key          varchar(255),
    requested_config         jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_summary           jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_code               varchar(100),
    error_message            text,
    retry_count              integer NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    max_retries              integer NOT NULL DEFAULT 3 CHECK (max_retries >= 0),
    worker_name              varchar(160),
    trace_id                 varchar(100),
    requested_by             uuid REFERENCES app_users(id) ON DELETE SET NULL,
    queued_at                timestamptz NOT NULL DEFAULT now(),
    started_at               timestamptz,
    heartbeat_at             timestamptz,
    completed_at             timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_processing_jobs_idempotency
    ON processing_jobs(project_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL;
CREATE INDEX ix_processing_jobs_queue ON processing_jobs(status, priority DESC, queued_at);
CREATE INDEX ix_processing_jobs_project ON processing_jobs(project_id, created_at DESC);

CREATE TABLE job_events (
    id                       bigserial PRIMARY KEY,
    job_id                   uuid NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    event_type               varchar(64) NOT NULL,
    stage                    varchar(100),
    progress_percent         numeric(5,2) CHECK (progress_percent IS NULL OR progress_percent BETWEEN 0 AND 100),
    level                    varchar(20) NOT NULL DEFAULT 'info',
    message                  text,
    payload                  jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_job_events_job ON job_events(job_id, id);

CREATE TABLE job_artifacts (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id                   uuid NOT NULL REFERENCES processing_jobs(id) ON DELETE CASCADE,
    file_id                  uuid NOT NULL REFERENCES stored_files(id) ON DELETE RESTRICT,
    artifact_type            varchar(64) NOT NULL,
    label                    varchar(200),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_job_artifacts UNIQUE (job_id, file_id, artifact_type)
);

-- -----------------------------------------------------------------------------
-- Search runs and evidence results
-- -----------------------------------------------------------------------------

CREATE TABLE search_runs (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id                   uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    name                     varchar(240),
    logic_operator           varchar(16) NOT NULL DEFAULT 'AND',
    match_scope              varchar(32) NOT NULL DEFAULT 'evidence_block',
    search_mode              varchar(32) NOT NULL DEFAULT 'hybrid',
    configuration            jsonb NOT NULL DEFAULT '{}'::jsonb,
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz
);

CREATE INDEX ix_search_runs_project ON search_runs(project_id, created_at DESC);

CREATE TABLE search_terms (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    search_run_id            uuid NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
    position                 integer NOT NULL CHECK (position >= 0),
    term_text                text NOT NULL,
    normalized_text          text,
    language                 varchar(20),
    is_required              boolean NOT NULL DEFAULT true,
    aliases                  jsonb NOT NULL DEFAULT '[]'::jsonb,
    options                  jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_search_terms_position UNIQUE (search_run_id, position)
);

CREATE TABLE search_results (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    search_run_id            uuid NOT NULL REFERENCES search_runs(id) ON DELETE CASCADE,
    result_no                integer NOT NULL CHECK (result_no > 0),
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    block_id                 uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    table_id                 uuid REFERENCES document_tables(id) ON DELETE SET NULL,
    figure_id                uuid REFERENCES document_figures(id) ON DELETE SET NULL,
    evidence_type            varchar(32) NOT NULL,
    previous_context         text,
    matched_context          text NOT NULL,
    next_context             text,
    matched_terms            jsonb NOT NULL DEFAULT '[]'::jsonb,
    match_details            jsonb NOT NULL DEFAULT '{}'::jsonb,
    score                    numeric,
    bbox                     jsonb,
    review_status            varchar(32) NOT NULL DEFAULT 'pending',
    is_included              boolean NOT NULL DEFAULT true,
    reviewed_by              uuid REFERENCES app_users(id) ON DELETE SET NULL,
    reviewed_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_search_results_number UNIQUE (search_run_id, result_no),
    CONSTRAINT ck_search_result_source CHECK (
        block_id IS NOT NULL OR table_id IS NOT NULL OR figure_id IS NOT NULL
    )
);

CREATE INDEX ix_search_results_document ON search_results(search_run_id, document_version_id, page_id);
CREATE INDEX ix_search_results_review ON search_results(search_run_id, review_status, is_included);

-- -----------------------------------------------------------------------------
-- Project terminology and configurable field schemas
-- -----------------------------------------------------------------------------

CREATE TABLE term_categories (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    code                     varchar(100) NOT NULL,
    name                     varchar(200) NOT NULL,
    description              text,
    color                    varchar(32),
    position                 integer NOT NULL DEFAULT 0,
    settings                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_term_categories UNIQUE (project_id, code)
);

CREATE TABLE terms (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    category_id              uuid NOT NULL REFERENCES term_categories(id) ON DELETE RESTRICT,
    canonical_name           text NOT NULL,
    normalized_name          text,
    definition               text,
    language                 varchar(20),
    data_type                varchar(32),
    semantic_role            varchar(32),
    preferred_unit_id        uuid REFERENCES units(id) ON DELETE SET NULL,
    indicator_direction      varchar(32),
    status                   varchar(32) NOT NULL DEFAULT 'candidate',
    is_selected              boolean NOT NULL DEFAULT false,
    include_in_model         boolean NOT NULL DEFAULT false,
    include_in_score         boolean NOT NULL DEFAULT false,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    deleted_at               timestamptz
);

CREATE UNIQUE INDEX uq_terms_name
    ON terms(project_id, category_id, lower(canonical_name))
    WHERE deleted_at IS NULL;
CREATE INDEX ix_terms_project_status ON terms(project_id, status, is_selected);
CREATE INDEX ix_terms_name_trgm ON terms USING gin(canonical_name gin_trgm_ops);

CREATE TABLE term_aliases (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    term_id                  uuid NOT NULL REFERENCES terms(id) ON DELETE CASCADE,
    alias_text               text NOT NULL,
    normalized_alias         text,
    language                 varchar(20),
    source                   varchar(50) NOT NULL DEFAULT 'system_suggestion',
    status                   varchar(32) NOT NULL DEFAULT 'pending',
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_term_aliases_text ON term_aliases(term_id, lower(alias_text));
CREATE INDEX ix_term_aliases_trgm ON term_aliases USING gin(alias_text gin_trgm_ops);

CREATE TABLE term_occurrences (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    term_id                  uuid REFERENCES terms(id) ON DELETE SET NULL,
    suggested_category_id    uuid REFERENCES term_categories(id) ON DELETE SET NULL,
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    block_id                 uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    table_cell_id            uuid REFERENCES document_table_cells(id) ON DELETE SET NULL,
    figure_id                uuid REFERENCES document_figures(id) ON DELETE SET NULL,
    original_text            text NOT NULL,
    normalized_text          text,
    context_text             text,
    char_start               integer CHECK (char_start IS NULL OR char_start >= 0),
    char_end                 integer CHECK (char_end IS NULL OR char_end >= 0),
    occurrence_count         integer NOT NULL DEFAULT 1 CHECK (occurrence_count > 0),
    extraction_method        varchar(64),
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_term_occurrence_source CHECK (
        block_id IS NOT NULL OR table_cell_id IS NOT NULL OR figure_id IS NOT NULL
    ),
    CONSTRAINT ck_term_occurrence_offsets CHECK (
        char_start IS NULL OR char_end IS NULL OR char_end >= char_start
    )
);

CREATE INDEX ix_term_occurrences_term ON term_occurrences(project_id, term_id);
CREATE INDEX ix_term_occurrences_document ON term_occurrences(document_version_id, page_id);
CREATE INDEX ix_term_occurrences_text_trgm ON term_occurrences USING gin(original_text gin_trgm_ops);

CREATE TABLE term_review_events (
    id                       bigserial PRIMARY KEY,
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    term_id                  uuid REFERENCES terms(id) ON DELETE SET NULL,
    action                   varchar(50) NOT NULL,
    related_term_ids         jsonb NOT NULL DEFAULT '[]'::jsonb,
    before_value             jsonb,
    after_value              jsonb,
    reason                   text,
    actor_id                 uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_term_review_events_term ON term_review_events(project_id, term_id, created_at DESC);

CREATE TABLE field_schemas (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_no               integer NOT NULL CHECK (version_no > 0),
    name                     varchar(240) NOT NULL,
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    parent_schema_id         uuid REFERENCES field_schemas(id) ON DELETE SET NULL,
    source_search_run_id     uuid REFERENCES search_runs(id) ON DELETE SET NULL,
    settings                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    frozen_by                uuid REFERENCES app_users(id) ON DELETE SET NULL,
    frozen_at                timestamptz,
    CONSTRAINT uq_field_schemas_version UNIQUE (project_id, version_no)
);

CREATE TABLE field_definitions (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    field_schema_id          uuid NOT NULL REFERENCES field_schemas(id) ON DELETE CASCADE,
    source_term_id           uuid REFERENCES terms(id) ON DELETE SET NULL,
    field_key                varchar(160) NOT NULL,
    display_name             varchar(240) NOT NULL,
    description              text,
    category_code            varchar(100),
    semantic_role            varchar(32) NOT NULL DEFAULT 'feature',
    data_type                varchar(32) NOT NULL DEFAULT 'text',
    preferred_unit_id        uuid REFERENCES units(id) ON DELETE SET NULL,
    indicator_direction      varchar(32),
    is_required              boolean NOT NULL DEFAULT false,
    is_identifier            boolean NOT NULL DEFAULT false,
    include_in_model         boolean NOT NULL DEFAULT false,
    include_in_score         boolean NOT NULL DEFAULT false,
    position                 integer NOT NULL DEFAULT 0,
    extraction_config        jsonb NOT NULL DEFAULT '{}'::jsonb,
    validation_rules         jsonb NOT NULL DEFAULT '{}'::jsonb,
    display_config           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_field_definitions_key UNIQUE (field_schema_id, field_key)
);

CREATE INDEX ix_field_definitions_schema ON field_definitions(field_schema_id, position);

CREATE TABLE field_options (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    field_definition_id      uuid NOT NULL REFERENCES field_definitions(id) ON DELETE CASCADE,
    option_value             text NOT NULL,
    option_label             text NOT NULL,
    position                 integer NOT NULL DEFAULT 0,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_field_options_value UNIQUE (field_definition_id, option_value)
);

-- Frozen field schemas are immutable. A changed schema must be copied to a new version.
CREATE OR REPLACE FUNCTION ensure_field_definition_mutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_schema_id uuid;
    target_status varchar(32);
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_schema_id := OLD.field_schema_id;
    ELSE
        target_schema_id := NEW.field_schema_id;
    END IF;

    SELECT status INTO target_status FROM field_schemas WHERE id = target_schema_id;
    IF target_status IN ('frozen', 'archived') THEN
        RAISE EXCEPTION 'Field schema % is immutable in status %', target_schema_id, target_status;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION ensure_field_option_mutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_definition_id uuid;
    target_schema_id uuid;
    target_status varchar(32);
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_definition_id := OLD.field_definition_id;
    ELSE
        target_definition_id := NEW.field_definition_id;
    END IF;

    SELECT field_schema_id INTO target_schema_id
    FROM field_definitions
    WHERE id = target_definition_id;

    SELECT status INTO target_status FROM field_schemas WHERE id = target_schema_id;
    IF target_status IN ('frozen', 'archived') THEN
        RAISE EXCEPTION 'Field schema % is immutable in status %', target_schema_id, target_status;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_field_definitions_mutable
BEFORE INSERT OR UPDATE OR DELETE ON field_definitions
FOR EACH ROW EXECUTE FUNCTION ensure_field_definition_mutable();

CREATE TRIGGER trg_field_options_mutable
BEFORE INSERT OR UPDATE OR DELETE ON field_options
FOR EACH ROW EXECUTE FUNCTION ensure_field_option_mutable();

-- -----------------------------------------------------------------------------
-- Extraction runs, atomic values and evidence
-- -----------------------------------------------------------------------------

CREATE TABLE extraction_runs (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    field_schema_id          uuid NOT NULL REFERENCES field_schemas(id) ON DELETE RESTRICT,
    search_run_id            uuid REFERENCES search_runs(id) ON DELETE SET NULL,
    job_id                   uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    name                     varchar(240),
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    configuration            jsonb NOT NULL DEFAULT '{}'::jsonb,
    extractor_name           varchar(160),
    extractor_version        varchar(100),
    prompt_version           varchar(100),
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz
);

CREATE INDEX ix_extraction_runs_project ON extraction_runs(project_id, created_at DESC);

CREATE TABLE extraction_records (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_run_id        uuid NOT NULL REFERENCES extraction_runs(id) ON DELETE CASCADE,
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    field_definition_id      uuid NOT NULL REFERENCES field_definitions(id) ON DELETE RESTRICT,
    sample_key               varchar(255) NOT NULL,
    group_key                varchar(255),
    timepoint_key            varchar(255),
    raw_value                text,
    raw_unit_text            varchar(160),
    parsed_value             jsonb NOT NULL DEFAULT '{}'::jsonb,
    normalized_value         jsonb NOT NULL DEFAULT '{}'::jsonb,
    ml_value                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    normalized_unit_id       uuid REFERENCES units(id) ON DELETE SET NULL,
    value_type               varchar(32) NOT NULL DEFAULT 'text',
    numeric_value            numeric,
    range_min                numeric,
    range_max                numeric,
    mean_value               numeric,
    standard_deviation       numeric,
    significance_marker      varchar(100),
    extraction_method        varchar(64) NOT NULL,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    review_status            varchar(32) NOT NULL DEFAULT 'pending',
    is_image_estimate        boolean NOT NULL DEFAULT false,
    is_missing               boolean NOT NULL DEFAULT false,
    notes                    text,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    reviewed_by              uuid REFERENCES app_users(id) ON DELETE SET NULL,
    reviewed_at              timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_extraction_range CHECK (
        range_min IS NULL OR range_max IS NULL OR range_max >= range_min
    )
);

CREATE INDEX ix_extraction_records_run ON extraction_records(extraction_run_id, sample_key);
CREATE INDEX ix_extraction_records_field ON extraction_records(field_definition_id, review_status);
CREATE INDEX ix_extraction_records_document ON extraction_records(document_version_id);

-- Source identity and verbatim source values are immutable after insertion.
CREATE OR REPLACE FUNCTION preserve_extraction_source()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.extraction_run_id IS DISTINCT FROM OLD.extraction_run_id
       OR NEW.document_version_id IS DISTINCT FROM OLD.document_version_id
       OR NEW.field_definition_id IS DISTINCT FROM OLD.field_definition_id
       OR NEW.sample_key IS DISTINCT FROM OLD.sample_key
       OR NEW.raw_value IS DISTINCT FROM OLD.raw_value
       OR NEW.raw_unit_text IS DISTINCT FROM OLD.raw_unit_text THEN
        RAISE EXCEPTION 'Extraction source identity and raw values are immutable; create a new record instead';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_extraction_records_preserve_source
BEFORE UPDATE ON extraction_records
FOR EACH ROW EXECUTE FUNCTION preserve_extraction_source();

CREATE TABLE extraction_evidence (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    extraction_record_id     uuid NOT NULL REFERENCES extraction_records(id) ON DELETE CASCADE,
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    block_id                 uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    table_cell_id            uuid REFERENCES document_table_cells(id) ON DELETE SET NULL,
    figure_id                uuid REFERENCES document_figures(id) ON DELETE SET NULL,
    evidence_type            varchar(32) NOT NULL,
    relation_type            varchar(32) NOT NULL DEFAULT 'supports',
    previous_context         text,
    evidence_text            text NOT NULL,
    next_context             text,
    bbox                     jsonb,
    is_primary               boolean NOT NULL DEFAULT false,
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_extraction_evidence_source CHECK (
        block_id IS NOT NULL OR table_cell_id IS NOT NULL OR figure_id IS NOT NULL
    )
);

CREATE INDEX ix_extraction_evidence_record ON extraction_evidence(extraction_record_id, is_primary DESC);
CREATE INDEX ix_extraction_evidence_document ON extraction_evidence(document_version_id, page_id);

-- -----------------------------------------------------------------------------
-- Editable and versioned datasets
-- -----------------------------------------------------------------------------

CREATE TABLE datasets (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name                     varchar(240) NOT NULL,
    description              text,
    purpose                  varchar(50) NOT NULL DEFAULT 'research',
    status                   varchar(32) NOT NULL DEFAULT 'active',
    settings                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    deleted_at               timestamptz
);

CREATE INDEX ix_datasets_project ON datasets(project_id, created_at DESC);

CREATE TABLE dataset_versions (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_id               uuid NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    version_no               integer NOT NULL CHECK (version_no > 0),
    parent_version_id        uuid REFERENCES dataset_versions(id) ON DELETE SET NULL,
    field_schema_id          uuid REFERENCES field_schemas(id) ON DELETE SET NULL,
    source_extraction_run_id uuid REFERENCES extraction_runs(id) ON DELETE SET NULL,
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    change_summary           text,
    row_count                bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    field_count              integer NOT NULL DEFAULT 0 CHECK (field_count >= 0),
    content_sha256           char(64),
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    frozen_by                uuid REFERENCES app_users(id) ON DELETE SET NULL,
    frozen_at                timestamptz,
    CONSTRAINT uq_dataset_versions UNIQUE (dataset_id, version_no),
    CONSTRAINT ck_dataset_version_hash CHECK (
        content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX ix_dataset_versions_dataset ON dataset_versions(dataset_id, version_no DESC);
CREATE INDEX ix_dataset_versions_status ON dataset_versions(status, created_at DESC);

CREATE TABLE dataset_fields (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id       uuid NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
    source_field_id          uuid REFERENCES field_definitions(id) ON DELETE SET NULL,
    field_key                varchar(160) NOT NULL,
    display_name             varchar(240) NOT NULL,
    data_type                varchar(32) NOT NULL DEFAULT 'text',
    semantic_role            varchar(32) NOT NULL DEFAULT 'feature',
    unit_id                  uuid REFERENCES units(id) ON DELETE SET NULL,
    position                 integer NOT NULL DEFAULT 0,
    is_required              boolean NOT NULL DEFAULT false,
    is_hidden                boolean NOT NULL DEFAULT false,
    validation_rules         jsonb NOT NULL DEFAULT '{}'::jsonb,
    display_config           jsonb NOT NULL DEFAULT '{}'::jsonb,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dataset_fields_key UNIQUE (dataset_version_id, field_key)
);

CREATE INDEX ix_dataset_fields_version ON dataset_fields(dataset_version_id, position);

CREATE TABLE dataset_rows (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_version_id       uuid NOT NULL REFERENCES dataset_versions(id) ON DELETE CASCADE,
    row_no                   bigint NOT NULL CHECK (row_no > 0),
    row_key                  varchar(255) NOT NULL,
    source_document_id       uuid REFERENCES documents(id) ON DELETE SET NULL,
    source_document_version_id uuid REFERENCES document_versions(id) ON DELETE SET NULL,
    source_sample_key        varchar(255),
    review_status            varchar(32) NOT NULL DEFAULT 'pending',
    is_deleted               boolean NOT NULL DEFAULT false,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dataset_rows_number UNIQUE (dataset_version_id, row_no),
    CONSTRAINT uq_dataset_rows_key UNIQUE (dataset_version_id, row_key)
);

CREATE INDEX ix_dataset_rows_version ON dataset_rows(dataset_version_id, row_no);
CREATE INDEX ix_dataset_rows_document ON dataset_rows(source_document_id);

CREATE TABLE dataset_cells (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    row_id                   uuid NOT NULL REFERENCES dataset_rows(id) ON DELETE CASCADE,
    field_id                 uuid NOT NULL REFERENCES dataset_fields(id) ON DELETE CASCADE,
    source_extraction_record_id uuid REFERENCES extraction_records(id) ON DELETE SET NULL,
    raw_value                text,
    raw_unit_text            varchar(160),
    normalized_value         jsonb NOT NULL DEFAULT '{}'::jsonb,
    ml_value                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    value_text               text,
    value_number             numeric,
    value_boolean            boolean,
    value_date               date,
    value_json               jsonb,
    range_min                numeric,
    range_max                numeric,
    mean_value               numeric,
    standard_deviation       numeric,
    significance_marker      varchar(100),
    unit_id                  uuid REFERENCES units(id) ON DELETE SET NULL,
    value_source             varchar(32) NOT NULL DEFAULT 'extracted',
    review_status            varchar(32) NOT NULL DEFAULT 'pending',
    confidence               numeric(5,4) CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
    is_missing               boolean NOT NULL DEFAULT false,
    is_image_estimate        boolean NOT NULL DEFAULT false,
    is_manually_modified     boolean NOT NULL DEFAULT false,
    notes                    text,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    modified_by              uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_dataset_cells UNIQUE (row_id, field_id),
    CONSTRAINT ck_dataset_cell_range CHECK (
        range_min IS NULL OR range_max IS NULL OR range_max >= range_min
    )
);

CREATE INDEX ix_dataset_cells_field_number ON dataset_cells(field_id, value_number) WHERE value_number IS NOT NULL;
CREATE INDEX ix_dataset_cells_review ON dataset_cells(review_status, is_missing, is_image_estimate);
CREATE INDEX ix_dataset_cells_extraction ON dataset_cells(source_extraction_record_id);

CREATE TABLE dataset_cell_evidence (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    dataset_cell_id          uuid NOT NULL REFERENCES dataset_cells(id) ON DELETE CASCADE,
    extraction_evidence_id   uuid REFERENCES extraction_evidence(id) ON DELETE SET NULL,
    document_version_id      uuid NOT NULL REFERENCES document_versions(id) ON DELETE CASCADE,
    page_id                  uuid NOT NULL REFERENCES document_pages(id) ON DELETE CASCADE,
    block_id                 uuid REFERENCES document_blocks(id) ON DELETE SET NULL,
    table_cell_id            uuid REFERENCES document_table_cells(id) ON DELETE SET NULL,
    figure_id                uuid REFERENCES document_figures(id) ON DELETE SET NULL,
    evidence_text            text NOT NULL,
    bbox                     jsonb,
    is_primary               boolean NOT NULL DEFAULT false,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_dataset_cell_evidence_source CHECK (
        extraction_evidence_id IS NOT NULL OR block_id IS NOT NULL OR table_cell_id IS NOT NULL OR figure_id IS NOT NULL
    )
);

CREATE INDEX ix_dataset_cell_evidence_cell ON dataset_cell_evidence(dataset_cell_id, is_primary DESC);

CREATE TABLE conversion_records (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    extraction_record_id     uuid REFERENCES extraction_records(id) ON DELETE SET NULL,
    dataset_cell_id          uuid REFERENCES dataset_cells(id) ON DELETE SET NULL,
    rule_id                  uuid REFERENCES unit_conversion_rules(id) ON DELETE RESTRICT,
    source_value             jsonb NOT NULL,
    source_unit_text         varchar(160),
    source_unit_id           uuid REFERENCES units(id) ON DELETE SET NULL,
    target_value             jsonb NOT NULL,
    target_unit_id           uuid NOT NULL REFERENCES units(id) ON DELETE RESTRICT,
    formula_used             text NOT NULL,
    context_used             jsonb NOT NULL DEFAULT '{}'::jsonb,
    status                   varchar(32) NOT NULL DEFAULT 'pending',
    confirmed_by             uuid REFERENCES app_users(id) ON DELETE SET NULL,
    confirmed_at             timestamptz,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_conversion_record_owner CHECK (
        extraction_record_id IS NOT NULL OR dataset_cell_id IS NOT NULL
    )
);

CREATE INDEX ix_conversion_records_project ON conversion_records(project_id, created_at DESC);
CREATE INDEX ix_conversion_records_cell ON conversion_records(dataset_cell_id);

-- Enforce that fields/rows/cells of a frozen dataset version are immutable.
CREATE OR REPLACE FUNCTION ensure_dataset_direct_mutable()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_version_id uuid;
    target_status varchar(32);
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_version_id := OLD.dataset_version_id;
    ELSE
        target_version_id := NEW.dataset_version_id;
    END IF;

    SELECT status INTO target_status
    FROM dataset_versions
    WHERE id = target_version_id;

    IF target_status IN ('frozen', 'archived') THEN
        RAISE EXCEPTION 'Dataset version % is immutable in status %', target_version_id, target_status;
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION ensure_dataset_cell_mutable_and_consistent()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    target_row_id uuid;
    target_field_id uuid;
    row_version_id uuid;
    field_version_id uuid;
    target_status varchar(32);
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_row_id := OLD.row_id;
        target_field_id := OLD.field_id;
    ELSE
        target_row_id := NEW.row_id;
        target_field_id := NEW.field_id;
    END IF;

    SELECT dataset_version_id INTO row_version_id FROM dataset_rows WHERE id = target_row_id;
    SELECT dataset_version_id INTO field_version_id FROM dataset_fields WHERE id = target_field_id;

    IF row_version_id IS NULL OR field_version_id IS NULL OR row_version_id <> field_version_id THEN
        RAISE EXCEPTION 'Dataset cell row and field must belong to the same dataset version';
    END IF;

    SELECT status INTO target_status FROM dataset_versions WHERE id = row_version_id;
    IF target_status IN ('frozen', 'archived') THEN
        RAISE EXCEPTION 'Dataset version % is immutable in status %', row_version_id, target_status;
    END IF;

    IF TG_OP = 'UPDATE'
       AND OLD.source_extraction_record_id IS NOT NULL
       AND (
           NEW.raw_value IS DISTINCT FROM OLD.raw_value
           OR NEW.raw_unit_text IS DISTINCT FROM OLD.raw_unit_text
           OR NEW.source_extraction_record_id IS DISTINCT FROM OLD.source_extraction_record_id
       ) THEN
        RAISE EXCEPTION 'Extracted raw value, raw unit and source record are immutable; edit normalized or typed values instead';
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER trg_dataset_fields_mutable
BEFORE INSERT OR UPDATE OR DELETE ON dataset_fields
FOR EACH ROW EXECUTE FUNCTION ensure_dataset_direct_mutable();

CREATE TRIGGER trg_dataset_rows_mutable
BEFORE INSERT OR UPDATE OR DELETE ON dataset_rows
FOR EACH ROW EXECUTE FUNCTION ensure_dataset_direct_mutable();

CREATE TRIGGER trg_dataset_cells_mutable
BEFORE INSERT OR UPDATE OR DELETE ON dataset_cells
FOR EACH ROW EXECUTE FUNCTION ensure_dataset_cell_mutable_and_consistent();

-- -----------------------------------------------------------------------------
-- Machine learning, predictions, explanations and optimization
-- -----------------------------------------------------------------------------

CREATE TABLE ml_runs (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    dataset_version_id       uuid NOT NULL REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    job_id                   uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    name                     varchar(240) NOT NULL,
    task_type                varchar(50) NOT NULL,
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    random_seed              bigint,
    split_strategy           varchar(64) NOT NULL DEFAULT 'group_kfold',
    group_field_key          varchar(160),
    split_config             jsonb NOT NULL DEFAULT '{}'::jsonb,
    preprocessing_config     jsonb NOT NULL DEFAULT '{}'::jsonb,
    augmentation_config      jsonb NOT NULL DEFAULT '{}'::jsonb,
    environment_snapshot     jsonb NOT NULL DEFAULT '{}'::jsonb,
    metrics_summary          jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz
);

CREATE INDEX ix_ml_runs_project ON ml_runs(project_id, created_at DESC);
CREATE INDEX ix_ml_runs_dataset ON ml_runs(dataset_version_id, status);

CREATE TABLE ml_run_fields (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ml_run_id                uuid NOT NULL REFERENCES ml_runs(id) ON DELETE CASCADE,
    dataset_field_id         uuid NOT NULL REFERENCES dataset_fields(id) ON DELETE RESTRICT,
    role                     varchar(32) NOT NULL,
    position                 integer NOT NULL DEFAULT 0,
    transformation_config    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_ml_run_fields UNIQUE (ml_run_id, dataset_field_id, role)
);

CREATE INDEX ix_ml_run_fields_run ON ml_run_fields(ml_run_id, role, position);

CREATE TABLE ml_models (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ml_run_id                uuid NOT NULL REFERENCES ml_runs(id) ON DELETE CASCADE,
    model_no                 integer NOT NULL CHECK (model_no > 0),
    display_name             varchar(200) NOT NULL,
    algorithm_code           varchar(100) NOT NULL,
    algorithm_version        varchar(100),
    status                   varchar(32) NOT NULL DEFAULT 'pending',
    hyperparameters          jsonb NOT NULL DEFAULT '{}'::jsonb,
    fitted_parameters        jsonb NOT NULL DEFAULT '{}'::jsonb,
    artifact_file_id         uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    artifact_sha256          char(64),
    is_selected              boolean NOT NULL DEFAULT false,
    selection_reason         text,
    training_seconds         numeric,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz,
    CONSTRAINT uq_ml_models_number UNIQUE (ml_run_id, model_no),
    CONSTRAINT ck_ml_model_hash CHECK (
        artifact_sha256 IS NULL OR artifact_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX ix_ml_models_run ON ml_models(ml_run_id, status, is_selected);

CREATE TABLE ml_metrics (
    id                       bigserial PRIMARY KEY,
    ml_model_id              uuid NOT NULL REFERENCES ml_models(id) ON DELETE CASCADE,
    dataset_field_id         uuid REFERENCES dataset_fields(id) ON DELETE SET NULL,
    split_name               varchar(32) NOT NULL,
    fold_no                  integer,
    metric_name              varchar(100) NOT NULL,
    metric_value             double precision,
    metric_payload           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ml_metrics_model ON ml_metrics(ml_model_id, split_name, metric_name);

CREATE TABLE ml_predictions (
    id                       bigserial PRIMARY KEY,
    ml_model_id              uuid NOT NULL REFERENCES ml_models(id) ON DELETE CASCADE,
    dataset_row_id           uuid REFERENCES dataset_rows(id) ON DELETE SET NULL,
    target_field_id          uuid REFERENCES dataset_fields(id) ON DELETE SET NULL,
    split_name               varchar(32),
    fold_no                  integer,
    actual_value             jsonb,
    predicted_value          jsonb NOT NULL,
    uncertainty              jsonb NOT NULL DEFAULT '{}'::jsonb,
    residual_value           double precision,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ml_predictions_model ON ml_predictions(ml_model_id, split_name);
CREATE INDEX ix_ml_predictions_row ON ml_predictions(dataset_row_id);

CREATE TABLE ml_explanations (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ml_model_id              uuid NOT NULL REFERENCES ml_models(id) ON DELETE CASCADE,
    method                   varchar(64) NOT NULL,
    scope                    varchar(32) NOT NULL,
    dataset_row_id           uuid REFERENCES dataset_rows(id) ON DELETE SET NULL,
    dataset_field_id         uuid REFERENCES dataset_fields(id) ON DELETE SET NULL,
    explanation_data         jsonb NOT NULL,
    artifact_file_id         uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_ml_explanations_model ON ml_explanations(ml_model_id, method, scope);

CREATE TABLE optimization_runs (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    ml_model_id              uuid NOT NULL REFERENCES ml_models(id) ON DELETE RESTRICT,
    job_id                   uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    name                     varchar(240) NOT NULL,
    method                   varchar(64) NOT NULL,
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    objective_config         jsonb NOT NULL,
    constraint_config        jsonb NOT NULL DEFAULT '{}'::jsonb,
    search_config            jsonb NOT NULL DEFAULT '{}'::jsonb,
    result_summary           jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz
);

CREATE INDEX ix_optimization_runs_project ON optimization_runs(project_id, created_at DESC);

CREATE TABLE optimization_candidates (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    optimization_run_id      uuid NOT NULL REFERENCES optimization_runs(id) ON DELETE CASCADE,
    rank_no                  integer NOT NULL CHECK (rank_no > 0),
    input_values             jsonb NOT NULL,
    predicted_values         jsonb NOT NULL,
    uncertainty              jsonb NOT NULL DEFAULT '{}'::jsonb,
    objective_score          double precision,
    is_feasible              boolean NOT NULL DEFAULT true,
    constraint_violations    jsonb NOT NULL DEFAULT '[]'::jsonb,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_optimization_candidates_rank UNIQUE (optimization_run_id, rank_no)
);

-- -----------------------------------------------------------------------------
-- Reports
-- -----------------------------------------------------------------------------

CREATE TABLE report_templates (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid REFERENCES organizations(id) ON DELETE CASCADE,
    name                     varchar(240) NOT NULL,
    code                     varchar(100) NOT NULL,
    version                  integer NOT NULL DEFAULT 1 CHECK (version > 0),
    template_file_id         uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    template_schema          jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_system                boolean NOT NULL DEFAULT false,
    is_active                boolean NOT NULL DEFAULT true,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX uq_report_templates_scope
    ON report_templates (
        COALESCE(organization_id, '00000000-0000-0000-0000-000000000000'::uuid),
        code,
        version
    );

CREATE TABLE reports (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    dataset_version_id       uuid REFERENCES dataset_versions(id) ON DELETE RESTRICT,
    ml_run_id                uuid REFERENCES ml_runs(id) ON DELETE SET NULL,
    optimization_run_id      uuid REFERENCES optimization_runs(id) ON DELETE SET NULL,
    report_template_id       uuid REFERENCES report_templates(id) ON DELETE SET NULL,
    job_id                   uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    version_no               integer NOT NULL CHECK (version_no > 0),
    title                    varchar(300) NOT NULL,
    status                   varchar(32) NOT NULL DEFAULT 'draft',
    configuration            jsonb NOT NULL DEFAULT '{}'::jsonb,
    output_file_id           uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    content_sha256           char(64),
    generated_by             uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now(),
    completed_at             timestamptz,
    CONSTRAINT uq_reports_version UNIQUE (project_id, title, version_no),
    CONSTRAINT ck_report_hash CHECK (
        content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'
    )
);

CREATE INDEX ix_reports_project ON reports(project_id, created_at DESC);

CREATE TABLE report_assets (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id                uuid NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
    asset_type               varchar(64) NOT NULL,
    section_key              varchar(160),
    title                    text,
    data_payload             jsonb NOT NULL DEFAULT '{}'::jsonb,
    file_id                  uuid REFERENCES stored_files(id) ON DELETE SET NULL,
    position                 integer NOT NULL DEFAULT 0,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_report_assets_report ON report_assets(report_id, position);

-- -----------------------------------------------------------------------------
-- External services, audit and integration events
-- -----------------------------------------------------------------------------

CREATE TABLE external_service_configs (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id               uuid REFERENCES projects(id) ON DELETE CASCADE,
    service_type             varchar(64) NOT NULL,
    provider                 varchar(100) NOT NULL,
    name                     varchar(200) NOT NULL,
    secret_reference         text,
    endpoint_url             text,
    configuration            jsonb NOT NULL DEFAULT '{}'::jsonb,
    is_enabled               boolean NOT NULL DEFAULT true,
    created_by               uuid REFERENCES app_users(id) ON DELETE SET NULL,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_external_service_configs_scope ON external_service_configs(organization_id, project_id, service_type);

CREATE TABLE external_calls (
    id                       bigserial PRIMARY KEY,
    project_id               uuid NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    job_id                   uuid REFERENCES processing_jobs(id) ON DELETE SET NULL,
    service_config_id        uuid REFERENCES external_service_configs(id) ON DELETE SET NULL,
    provider                 varchar(100) NOT NULL,
    model_name               varchar(160),
    operation                varchar(100) NOT NULL,
    prompt_version           varchar(100),
    input_sha256             char(64),
    output_sha256            char(64),
    input_units              integer,
    output_units             integer,
    latency_ms               integer CHECK (latency_ms IS NULL OR latency_ms >= 0),
    status                   varchar(32) NOT NULL,
    error_code               varchar(100),
    error_message            text,
    metadata                 jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_external_calls_project ON external_calls(project_id, created_at DESC);
CREATE INDEX ix_external_calls_job ON external_calls(job_id);

CREATE TABLE audit_logs (
    id                       bigserial PRIMARY KEY,
    organization_id          uuid NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    project_id               uuid REFERENCES projects(id) ON DELETE CASCADE,
    actor_id                 uuid REFERENCES app_users(id) ON DELETE SET NULL,
    trace_id                 varchar(100),
    entity_type              varchar(100) NOT NULL,
    entity_id                uuid,
    action                   varchar(100) NOT NULL,
    before_value             jsonb,
    after_value              jsonb,
    reason                   text,
    client_ip                inet,
    user_agent               text,
    created_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_logs_project ON audit_logs(project_id, created_at DESC);
CREATE INDEX ix_audit_logs_entity ON audit_logs(entity_type, entity_id, created_at DESC);
CREATE INDEX ix_audit_logs_actor ON audit_logs(actor_id, created_at DESC);

CREATE TRIGGER trg_audit_logs_append_only
BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION prevent_row_mutation();

CREATE TABLE outbox_events (
    id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type           varchar(100) NOT NULL,
    aggregate_id             uuid NOT NULL,
    event_type               varchar(160) NOT NULL,
    payload                  jsonb NOT NULL,
    headers                  jsonb NOT NULL DEFAULT '{}'::jsonb,
    status                   varchar(32) NOT NULL DEFAULT 'pending',
    attempts                 integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at             timestamptz NOT NULL DEFAULT now(),
    published_at             timestamptz,
    last_error               text,
    created_at               timestamptz NOT NULL DEFAULT now(),
    updated_at               timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX ix_outbox_events_pending ON outbox_events(status, available_at) WHERE status = 'pending';

-- -----------------------------------------------------------------------------
-- Useful views
-- -----------------------------------------------------------------------------

CREATE VIEW latest_document_versions AS
SELECT DISTINCT ON (dv.document_id)
       dv.*
FROM document_versions dv
ORDER BY dv.document_id, dv.version_no DESC;

CREATE VIEW dataset_cell_values AS
SELECT
    dv.dataset_id,
    dv.id AS dataset_version_id,
    dv.version_no,
    dr.id AS row_id,
    dr.row_no,
    dr.row_key,
    df.id AS field_id,
    df.field_key,
    df.display_name,
    df.data_type,
    dc.id AS cell_id,
    dc.raw_value,
    dc.raw_unit_text,
    dc.normalized_value,
    dc.ml_value,
    dc.value_text,
    dc.value_number,
    dc.value_boolean,
    dc.value_date,
    dc.value_json,
    dc.range_min,
    dc.range_max,
    dc.mean_value,
    dc.standard_deviation,
    dc.unit_id,
    dc.review_status,
    dc.is_missing,
    dc.is_image_estimate,
    dc.is_manually_modified
FROM dataset_versions dv
JOIN dataset_rows dr ON dr.dataset_version_id = dv.id
JOIN dataset_cells dc ON dc.row_id = dr.id
JOIN dataset_fields df ON df.id = dc.field_id AND df.dataset_version_id = dv.id
WHERE dr.is_deleted = false;

-- -----------------------------------------------------------------------------
-- updated_at triggers
-- -----------------------------------------------------------------------------

CREATE TRIGGER trg_app_users_updated_at BEFORE UPDATE ON app_users
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_organizations_updated_at BEFORE UPDATE ON organizations
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_organization_members_updated_at BEFORE UPDATE ON organization_members
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_projects_updated_at BEFORE UPDATE ON projects
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_project_members_updated_at BEFORE UPDATE ON project_members
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_configuration_templates_updated_at BEFORE UPDATE ON configuration_templates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_units_updated_at BEFORE UPDATE ON units
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_unit_conversion_rules_updated_at BEFORE UPDATE ON unit_conversion_rules
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON documents
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_processing_jobs_updated_at BEFORE UPDATE ON processing_jobs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_search_runs_updated_at BEFORE UPDATE ON search_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_search_results_updated_at BEFORE UPDATE ON search_results
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_term_categories_updated_at BEFORE UPDATE ON term_categories
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_terms_updated_at BEFORE UPDATE ON terms
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_term_aliases_updated_at BEFORE UPDATE ON term_aliases
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_field_schemas_updated_at BEFORE UPDATE ON field_schemas
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_field_definitions_updated_at BEFORE UPDATE ON field_definitions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_extraction_runs_updated_at BEFORE UPDATE ON extraction_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_extraction_records_updated_at BEFORE UPDATE ON extraction_records
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_datasets_updated_at BEFORE UPDATE ON datasets
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_dataset_versions_updated_at BEFORE UPDATE ON dataset_versions
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_dataset_fields_updated_at BEFORE UPDATE ON dataset_fields
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_dataset_rows_updated_at BEFORE UPDATE ON dataset_rows
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_dataset_cells_updated_at BEFORE UPDATE ON dataset_cells
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_ml_runs_updated_at BEFORE UPDATE ON ml_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_ml_models_updated_at BEFORE UPDATE ON ml_models
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_optimization_runs_updated_at BEFORE UPDATE ON optimization_runs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_report_templates_updated_at BEFORE UPDATE ON report_templates
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_reports_updated_at BEFORE UPDATE ON reports
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_external_service_configs_updated_at BEFORE UPDATE ON external_service_configs
FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_outbox_events_updated_at BEFORE UPDATE ON outbox_events
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- -----------------------------------------------------------------------------
-- Table comments for maintainers
-- -----------------------------------------------------------------------------

COMMENT ON SCHEMA public IS 'Domain-neutral research document extraction and machine learning platform';
COMMENT ON TABLE configuration_templates IS 'Optional initialization templates; never a source of hard-coded industry fields';
COMMENT ON TABLE document_blocks IS 'Page-level structural blocks with coordinates and multilingual full-text index';
COMMENT ON TABLE field_schemas IS 'Versioned project field configuration used by extraction and datasets';
COMMENT ON TABLE extraction_records IS 'Staging atomic values; raw, normalized and ML representations remain separate';
COMMENT ON TABLE extraction_evidence IS 'One-to-many source evidence for every extracted value';
COMMENT ON TABLE dataset_versions IS 'Immutable after status becomes frozen or archived';
COMMENT ON TABLE dataset_fields IS 'Version-specific dynamic columns; supports adding/removing fields without DDL';
COMMENT ON TABLE dataset_cells IS 'Typed editable cells with provenance and review state';
COMMENT ON TABLE ml_runs IS 'Reproducible machine learning run bound to a frozen dataset version';
COMMENT ON TABLE audit_logs IS 'Append-only user and system audit trail';

COMMIT;
