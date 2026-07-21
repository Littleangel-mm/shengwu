export type User = {
  id: string
  email: string
  display_name: string
  status: string
}

export type Organization = {
  id: string
  name: string
  slug: string
  status: string
}

export type Project = {
  id: string
  organization_id: string
  name: string
  slug: string
  description?: string | null
  research_domain?: string | null
  default_language: string
  status: string
  settings?: Record<string, unknown>
  created_at: string
}

export type PrismaExclusionReason = {
  reason: string
  count: number
}

export type PrismaFlowData = {
  identified_databases: number
  identified_registers: number
  duplicates_removed: number
  records_screened: number
  records_excluded: number
  reports_sought: number
  reports_not_retrieved: number
  reports_assessed: number
  studies_included: number
  reports_excluded: PrismaExclusionReason[]
}

export type PrismaFlow = {
  project_id: string
  data: PrismaFlowData
  notes?: string | null
  exists: boolean
}

export type LineageNode = Record<string, unknown> | null

export type ReportLineage = {
  report: LineageNode
  search_run: LineageNode
  field_schema: LineageNode
  extraction_run: LineageNode
  dataset: LineageNode
  dataset_version: LineageNode
  ml_run: LineageNode
  ml_models: Record<string, unknown>[]
  optimization_run: LineageNode
  source_document_count: number
  source_files: {
    title?: string | null
    original_name?: string | null
    extension?: string | null
    byte_size?: number | null
    sha256?: string | null
  }[]
  hash_chain: { stage: string; sha256: string | string[] }[]
}

export type TokenResponse = {
  access_token: string
  expires_at: string
  user: User
}

export type ListResponse<T> = {
  items: T[]
  total: number
  offset: number
  limit: number
}

export type DocumentItem = {
  id: string
  title?: string | null
  document_type: string
  status: string
  language?: string | null
  version_id: string
  version_no: number
  parse_status: string
  page_count?: number | null
  original_name: string
  byte_size: number
  created_at: string
}

export type DocumentDetail = {
  document: {
    id: string
    project_id: string
    title?: string | null
    authors: string[]
    publication_year?: number | null
    publication_name?: string | null
    doi?: string | null
    language?: string | null
    status: string
  }
  version: {
    id: string
    version_no: number
    parse_status: string
    page_count?: number | null
    original_name?: string | null
    byte_size?: number | null
    media_type?: string | null
    metadata: Record<string, unknown>
  }
  pages: Array<{
    id: string
    page_no: number
    text_content?: string | null
    text_source: string
    width?: number | null
    height?: number | null
    ocr_confidence?: number | null
    metadata: Record<string, unknown>
  }>
  blocks: Array<{
    id: string
    page_id: string
    block_type: string
    sequence_no: number
    content_text: string
    bbox?: number[] | null
    confidence?: number | null
  }>
  tables: Array<{
    id: string
    page_id: string
    table_no: string
    title?: string | null
    row_count: number
    column_count: number
    bbox?: number[] | null
    confidence?: number | null
    cells: Array<{
      id: string
      row_index: number
      column_index: number
      row_span: number
      column_span: number
      raw_text?: string | null
      normalized_text?: string | null
    }>
  }>
  figures: Array<{
    id: string
    page_id: string
    figure_no: string
    title?: string | null
    caption?: string | null
    figure_type: string
    bbox?: number[] | null
    image_file_id?: string | null
    axis_metadata: Record<string, unknown>
    legend_metadata: Record<string, unknown>
    extracted_labels: unknown[]
  }>
  counts: { blocks: number; tables: number; figures: number }
}

export type JobItem = {
  id: string
  job_type: string
  status: string
  progress_percent: number | string
  current_stage?: string | null
  error_message?: string | null
  queued_at: string
  started_at?: string | null
  completed_at?: string | null
  updated_at: string
}

export type JobEvent = {
  id: number
  job_id: string
  event_type: string
  stage?: string | null
  progress_percent?: number | string | null
  level: string
  message?: string | null
  payload: Record<string, unknown>
  created_at: string
}

export type TaskAccepted = {
  resource_id: string
  job_id: string
  status: string
}

export type GenericRecord = Record<string, unknown> & { id: string }

export type SearchMode = 'exact' | 'fuzzy' | 'semantic' | 'hybrid'
export type SearchScope = 'evidence_block' | 'page' | 'document'
export type SearchRun = GenericRecord & {
  name?: string | null
  logic_operator: 'AND' | 'OR'
  match_scope: SearchScope
  search_mode: SearchMode
  configuration: { fuzzy_threshold?: number; semantic_threshold?: number }
  status: string
  terms: string[]
  result_count: number
  created_at: string
}
export type SearchResult = GenericRecord & {
  result_no: number
  document_id: string
  document_title?: string | null
  document_version_id: string
  page_id: string
  page_no: number
  evidence_type: string
  previous_context?: string | null
  matched_context: string
  next_context?: string | null
  matched_terms: Array<{
    term: string
    matched: boolean
    score: number
    variant?: string | null
    semantic_score?: number
  }>
  match_details: Record<string, unknown>
  score?: number | null
  bbox?: number[] | null
  review_status: 'pending' | 'confirmed' | 'excluded'
  is_included: boolean
}

export type TermCategory = {
  id: string
  project_id: string
  code: string
  name: string
  description?: string | null
  position?: number
}

export type Term = GenericRecord & {
  category_id: string
  canonical_name: string
  definition?: string | null
  language?: string | null
  data_type?: string | null
  semantic_role?: string | null
  status: string
  is_selected: boolean
  include_in_model: boolean
  include_in_score: boolean
  indicator_direction?: string | null
  aliases: Array<{ id?: string; alias_text: string } | string>
}

export type UnitItem = {
  id: string
  code: string
  name: string
  symbol?: string | null
  dimension?: string | null
}

export type FieldDefinition = {
  id?: string
  field_key: string
  display_name: string
  source_term_id?: string | null
  category_code?: string | null
  semantic_role: string
  data_type: 'text' | 'number' | 'boolean' | 'date' | 'category' | 'range'
  preferred_unit_id?: string | null
  indicator_direction?: string | null
  is_required: boolean
  is_identifier: boolean
  include_in_model: boolean
  include_in_score: boolean
  extraction_config: Record<string, unknown>
  validation_rules: Record<string, unknown>
}

export type FieldSchema = GenericRecord & {
  name: string
  version_no: number
  status: string
  source_search_run_id?: string | null
  settings: Record<string, unknown>
  fields?: FieldDefinition[]
}

export type FieldCandidate = {
  id: string
  display_name: string
  category?: string | null
  category_id?: string | null
  data_type: string
  suggested_role?: string | null
  suggested_unit?: string | null
  occurrence_count: number
  document_count: number
  confidence?: number | null
  examples: string[]
  aliases: string[]
}

export type CandidateFieldInput = {
  term_id: string
  field_key: string
  display_name: string
  semantic_role: string
  data_type: FieldDefinition['data_type']
  is_identifier: boolean
  include_in_model: boolean
  include_in_score: boolean
}

export type QualityFieldReport = {
  field_key: string
  display_name: string
  data_type: string
  value_count: number
  numeric_count: number
  samples_with_value: number
  completeness: number
  range_validity: number
  range_source: string
  expected_min?: number | null
  expected_max?: number | null
  out_of_range_count: number
  units_seen: string[]
  unit_conflict: boolean
}

export type QualityReport = {
  extraction_run_id: string
  status: string
  overall_score: number
  total_samples: number
  field_count: number
  completeness_avg: number
  range_validity_avg: number
  unit_conflict_fields: number
  conversion_counts: Record<string, number>
  fields: QualityFieldReport[]
}

export type ExtractionRun = GenericRecord & {
  name?: string | null
  field_schema_id: string
  search_run_id?: string | null
  status: string
  record_count?: number
  created_at: string
}

export type ExtractionRecord = GenericRecord & {
  extraction_run_id: string
  field_definition_id: string
  field_key?: string
  field_display_name?: string
  document_id?: string
  document_title?: string | null
  document_version_id: string
  page_no?: number | null
  bbox?: number[] | null
  evidence_text?: string | null
  sample_key: string
  group_key?: string | null
  timepoint_key?: string | null
  raw_value?: string | null
  parsed_value: Record<string, unknown>
  normalized_value: Record<string, unknown>
  ml_value: Record<string, unknown>
  confidence?: number | null
  review_status: 'pending' | 'confirmed' | 'modified' | 'doubtful' | 'excluded'
  notes?: string | null
}

export type DatasetSummary = GenericRecord & {
  name: string
  description?: string | null
  latest_version_id: string
  latest_version_no: number
  latest_version_status: string
  row_count: number
  field_count: number
}

export type DatasetField = {
  id: string
  field_key: string
  display_name: string
  data_type: string
  semantic_role: string
  unit_id?: string | null
  is_required: boolean
  position: number
}

export type DatasetCell = GenericRecord & {
  field_id: string
  raw_value?: string | null
  value_text?: string | null
  value_number?: number | null
  value_boolean?: boolean | null
  value_date?: string | null
  normalized_value?: Record<string, unknown> | null
  ml_value?: Record<string, unknown> | null
  unit_id?: string | null
  review_status: string
  is_missing: boolean
  notes?: string | null
  evidence?: Array<{
    id: string
    document_id?: string
    page_no?: number | null
    evidence_text?: string | null
    bbox?: number[] | null
  }>
}

export type DatasetVersionDetail = {
  dataset: DatasetSummary
  version: GenericRecord & {
    dataset_id: string
    version_no: number
    status: string
    row_count: number
    field_count: number
  }
  fields: DatasetField[]
  rows: Array<
    GenericRecord & {
      row_no: number
      row_key: string
      source_document_id?: string | null
      cells: Record<string, DatasetCell>
    }
  >
  offset: number
  limit: number
}

export type MLMetric = {
  id: string
  split_name: string
  metric_name: string
  metric_value: number
}

export type MLExplanation = {
  id: string
  method: string
  explanation_data: {
    features?: Array<{ feature?: string; name?: string; importance?: number; value?: number }>
  }
}

export type MLModel = GenericRecord & {
  algorithm_code: string
  is_selected: boolean
  hyperparameters: Record<string, unknown>
  metrics: MLMetric[]
  explanations: MLExplanation[]
}

export type MLRun = GenericRecord & {
  name: string
  dataset_version_id: string
  task_type: 'regression' | 'classification'
  status: string
  job_id?: string | null
  metrics_summary?: Record<string, unknown>
  created_at: string
  models?: MLModel[]
}

export type PredictionResult = {
  model_id: string
  target: string
  prediction: number | string
  task_type: string
  uncertainty: {
    standard_deviation?: number
    prediction_interval_95?: [number, number]
    confidence?: number
    entropy?: number
    probabilities?: Array<number | { label: string; probability: number }>
  }
}

export type OptimizationRun = GenericRecord & {
  name: string
  ml_model_id: string
  status: string
  job_id?: string | null
  objective: Record<string, unknown>
  constraints: Record<string, unknown>
  candidates?: Array<{
    id: string
    rank_no: number
    input_values: Record<string, unknown>
    predicted_values: Record<string, unknown>
    uncertainty: Record<string, unknown>
    objective_score: number
    is_feasible: boolean
  }>
}

export type ReportItem = GenericRecord & {
  title: string
  dataset_version_id: string
  ml_run_id?: string | null
  optimization_run_id?: string | null
  status: string
  job_id?: string | null
  created_at: string
}

export type SynonymClusterTerm = {
  id: string
  display_name: string
  category_id?: string | null
  category_name?: string | null
  occurrence_count?: number | null
}

export type SynonymCluster = {
  suggested_standard: SynonymClusterTerm
  similarity: number
  terms: SynonymClusterTerm[]
}

export type MemberItem = {
  user_id: string
  email: string
  display_name: string
  role: string
  status: string
}

export type ProjectMembership = {
  project_id: string
  project_role?: string | null
  organization_role?: string | null
  can_write: boolean
  can_manage_members: boolean
}

export class ApiError extends Error {
  status: number
  code: string
  details: unknown

  constructor(status: number, code: string, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.code = code
    this.details = details
  }
}

const API_PREFIX = import.meta.env.VITE_API_PREFIX || '/api/v1'
const TOKEN_KEY = 'shengwu_access_token'

export const session = {
  getToken: () => localStorage.getItem(TOKEN_KEY),
  setToken: (token: string) => localStorage.setItem(TOKEN_KEY, token),
  clear: () => localStorage.removeItem(TOKEN_KEY),
}

async function request<T>(
  path: string,
  options: RequestInit & { auth?: boolean } = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  const token = session.getToken()
  if (options.auth !== false && token) headers.set('Authorization', `Bearer ${token}`)
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_PREFIX}${path}`, { ...options, headers })
  if (!response.ok) {
    let payload: {
      error?: { code?: string; message?: string; details?: unknown }
    } = {}
    try {
      payload = await response.json()
    } catch {
      payload = {}
    }
    if (response.status === 401 && options.auth !== false) {
      window.dispatchEvent(new Event('shengwu:unauthorized'))
    }
    throw new ApiError(
      response.status,
      payload.error?.code || 'request_failed',
      payload.error?.message || `请求失败 (${response.status})`,
      payload.error?.details,
    )
  }
  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

const json = (body: unknown) => JSON.stringify(body)

async function authorizedBlob(path: string): Promise<Blob> {
  const headers = new Headers()
  const token = session.getToken()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(`${API_PREFIX}${path}`, { headers })
  if (!response.ok) {
    throw new ApiError(response.status, 'download_failed', '文件读取失败')
  }
  return response.blob()
}

async function downloadBlob(path: string, filename: string) {
  const blobUrl = URL.createObjectURL(await authorizedBlob(path))
  const anchor = document.createElement('a')
  anchor.href = blobUrl
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(blobUrl)
}

export const api = {
  login: (email: string, password: string) =>
    request<TokenResponse>('/auth/login', {
      method: 'POST',
      body: json({ email, password }),
      auth: false,
    }),
  register: (email: string, displayName: string, password: string) =>
    request<TokenResponse>('/auth/register', {
      method: 'POST',
      body: json({ email, display_name: displayName, password }),
      auth: false,
    }),
  me: () => request<User>('/auth/me'),
  health: () =>
    request<{ status: string; database?: string }>('/health/ready', { auth: false }),

  organizations: () => request<ListResponse<Organization>>('/organizations'),
  createOrganization: (name: string) =>
    request<Organization>('/organizations', { method: 'POST', body: json({ name }) }),
  projects: (organizationId?: string) =>
    request<ListResponse<Project>>(
      `/projects${organizationId ? `?organization_id=${organizationId}` : ''}`,
    ),
  project: (projectId: string) => request<Project>(`/projects/${projectId}`),
  createProject: (payload: {
    organization_id: string
    name: string
    description?: string
    research_domain?: string
  }) => request<Project>('/projects', { method: 'POST', body: json(payload) }),
  updateProject: (
    projectId: string,
    patch: { name?: string; description?: string; settings?: Record<string, unknown> },
  ) => request<Project>(`/projects/${projectId}`, { method: 'PATCH', body: json(patch) }),
  archiveProject: (projectId: string) =>
    request<Project>(`/projects/${projectId}/archive`, { method: 'POST' }),
  unarchiveProject: (projectId: string) =>
    request<Project>(`/projects/${projectId}/unarchive`, { method: 'POST' }),
  projectMembership: (projectId: string) =>
    request<ProjectMembership>(`/projects/${projectId}/membership`),
  projectMembers: (projectId: string) =>
    request<MemberItem[]>(`/projects/${projectId}/members`),
  inviteProjectMember: (projectId: string, email: string, role: string) =>
    request<MemberItem>(`/projects/${projectId}/members`, {
      method: 'POST',
      body: json({ email, role }),
    }),
  updateProjectMember: (projectId: string, userId: string, role: string) =>
    request<MemberItem>(`/projects/${projectId}/members/${userId}`, {
      method: 'PATCH',
      body: json({ role }),
    }),
  removeProjectMember: (projectId: string, userId: string) =>
    request<void>(`/projects/${projectId}/members/${userId}`, { method: 'DELETE' }),
  organizationMembers: (organizationId: string) =>
    request<MemberItem[]>(`/organizations/${organizationId}/members`),
  inviteOrganizationMember: (organizationId: string, email: string, role: string) =>
    request<MemberItem>(`/organizations/${organizationId}/members`, {
      method: 'POST',
      body: json({ email, role }),
    }),
  updateOrganizationMember: (organizationId: string, userId: string, role: string) =>
    request<MemberItem>(`/organizations/${organizationId}/members/${userId}`, {
      method: 'PATCH',
      body: json({ role }),
    }),
  removeOrganizationMember: (organizationId: string, userId: string) =>
    request<void>(`/organizations/${organizationId}/members/${userId}`, {
      method: 'DELETE',
    }),

  documents: (projectId: string) =>
    request<ListResponse<DocumentItem>>(`/projects/${projectId}/documents?limit=100`),
  documentDetail: (projectId: string, documentId: string) =>
    request<DocumentDetail>(`/projects/${projectId}/documents/${documentId}`),
  reparseDocument: (projectId: string, documentId: string) =>
    request<JobItem>(`/projects/${projectId}/documents/${documentId}/parse`, {
      method: 'POST',
    }),
  translateDocument: (projectId: string, versionId: string) =>
    request<TaskAccepted>(`/projects/${projectId}/document-versions/${versionId}/translate`, {
      method: 'POST',
      body: json({ target_language: 'zh-CN', overwrite: false }),
    }),
  downloadDocument: async (projectId: string, documentId: string, filename: string) => {
    const blobUrl = URL.createObjectURL(
      await authorizedBlob(`/projects/${projectId}/documents/${documentId}/source`),
    )
    const anchor = document.createElement('a')
    anchor.href = blobUrl
    anchor.download = filename
    anchor.click()
    URL.revokeObjectURL(blobUrl)
  },
  figureBlob: (projectId: string, documentId: string, figureId: string) =>
    authorizedBlob(`/projects/${projectId}/documents/${documentId}/figures/${figureId}/image`),
  pageImageBlob: (projectId: string, documentId: string, pageNo: number) =>
    authorizedBlob(`/projects/${projectId}/documents/${documentId}/pages/${pageNo}/image`),
  uploadDocuments: (projectId: string, files: FileList | File[]) => {
    const form = new FormData()
    Array.from(files).forEach((file) => form.append('files', file))
    return request<{ items: Array<Record<string, unknown>>; total: number }>(
      `/projects/${projectId}/documents/upload`,
      { method: 'POST', body: form },
    )
  },
  jobs: (projectId: string) =>
    request<ListResponse<JobItem>>(`/projects/${projectId}/jobs?limit=100`),
  jobEvents: (projectId: string, jobId: string) =>
    request<JobEvent[]>(`/projects/${projectId}/jobs/${jobId}/events`),
  runJob: (projectId: string, jobId: string) =>
    request<JobItem>(`/projects/${projectId}/jobs/${jobId}/run`, { method: 'POST' }),
  retryJob: (projectId: string, jobId: string) =>
    request<JobItem>(`/projects/${projectId}/jobs/${jobId}/retry`, { method: 'POST' }),

  searchRuns: (projectId: string) =>
    request<ListResponse<SearchRun>>(`/projects/${projectId}/search-runs?limit=100`),
  createSearch: (
    projectId: string,
    payload: {
      terms: string[]
      name?: string
      logic_operator: 'AND' | 'OR'
      match_scope: SearchScope
      search_mode: SearchMode
      fuzzy_threshold: number
      semantic_threshold: number
    },
  ) =>
    request<TaskAccepted>(`/projects/${projectId}/search-runs`, {
      method: 'POST',
      body: json(payload),
    }),
  searchResults: (projectId: string, runId: string) =>
    request<ListResponse<SearchResult>>(
      `/projects/${projectId}/search-runs/${runId}/results?limit=500`,
    ),
  reviewSearchResult: (
    projectId: string,
    runId: string,
    resultId: string,
    payload: { is_included: boolean; review_status: 'pending' | 'confirmed' | 'excluded' },
  ) =>
    request<SearchResult>(
      `/projects/${projectId}/search-runs/${runId}/results/${resultId}`,
      { method: 'PATCH', body: json(payload) },
    ),
  exportSearchPackage: (projectId: string, runId: string, name: string) =>
    downloadBlob(
      `/projects/${projectId}/search-runs/${runId}/export.xlsx`,
      `${name || 'search-package'}.xlsx`,
    ),
  termCategories: (projectId: string) =>
    request<TermCategory[]>(`/projects/${projectId}/term-categories`),
  createTermCategory: (projectId: string, payload: { code: string; name: string; description?: string }) =>
    request<TermCategory>(`/projects/${projectId}/term-categories`, {
      method: 'POST',
      body: json(payload),
    }),
  updateTermCategory: (projectId: string, categoryId: string, payload: Partial<TermCategory>) =>
    request<TermCategory>(`/projects/${projectId}/term-categories/${categoryId}`, {
      method: 'PATCH',
      body: json(payload),
    }),
  deleteTermCategory: (projectId: string, categoryId: string) =>
    request<void>(`/projects/${projectId}/term-categories/${categoryId}`, { method: 'DELETE' }),
  applyDefaultTermTemplate: (projectId: string) =>
    request<TermCategory[]>(`/projects/${projectId}/term-categories/apply-default-template`, {
      method: 'POST',
    }),
  synonymSuggestions: (projectId: string) =>
    request<SynonymCluster[]>(`/projects/${projectId}/terms/synonym-suggestions`),
  terms: (projectId: string, categoryId?: string, status?: string) => {
    const params = new URLSearchParams({ limit: '500' })
    if (categoryId) params.set('category_id', categoryId)
    if (status) params.set('status', status)
    return request<ListResponse<Term>>(`/projects/${projectId}/terms?${params}`)
  },
  term: (projectId: string, termId: string) =>
    request<Term>(`/projects/${projectId}/terms/${termId}`),
  createTerm: (projectId: string, payload: Omit<Term, 'id' | 'project_id' | 'include_in_model' | 'include_in_score'>) =>
    request<Term>(`/projects/${projectId}/terms`, { method: 'POST', body: json(payload) }),
  updateTerm: (projectId: string, termId: string, payload: Partial<Term> & { aliases?: string[] }) =>
    request<Term>(`/projects/${projectId}/terms/${termId}`, {
      method: 'PATCH',
      body: json(payload),
    }),
  deleteTerm: (projectId: string, termId: string) =>
    request<Record<string, unknown>>(`/projects/${projectId}/terms/${termId}`, {
      method: 'DELETE',
    }),
  mergeTerms: (projectId: string, targetTermId: string, sourceTermIds: string[], reason?: string) =>
    request<Term>(`/projects/${projectId}/terms/merge`, {
      method: 'POST',
      body: json({ target_term_id: targetTermId, source_term_ids: sourceTermIds, reason }),
    }),
  splitTerm: (
    projectId: string,
    termId: string,
    children: Array<{ category_id: string; canonical_name: string; aliases: string[] }>,
  ) =>
    request<Term[]>(`/projects/${projectId}/terms/${termId}/split`, {
      method: 'POST',
      body: json({ children }),
    }),
  discoverTerms: (projectId: string, searchRunId: string) =>
    request<TaskAccepted>(`/projects/${projectId}/term-discovery`, {
      method: 'POST',
      body: json({ search_run_id: searchRunId, min_occurrences: 2, max_candidates: 500 }),
    }),
  discoverFields: (
    projectId: string,
    options?: { search_run_id?: string | null; min_documents?: number; use_llm?: boolean },
  ) =>
    request<TaskAccepted>(`/projects/${projectId}/field-discovery`, {
      method: 'POST',
      body: json({
        search_run_id: options?.search_run_id ?? null,
        min_documents: options?.min_documents ?? 1,
        max_candidates: 200,
        use_llm: options?.use_llm ?? true,
      }),
    }),
  fieldCandidates: (projectId: string) =>
    request<FieldCandidate[]>(`/projects/${projectId}/field-candidates`),
  createFieldSchemaFromCandidates: (
    projectId: string,
    payload: { name: string; candidates: CandidateFieldInput[] },
  ) =>
    request<FieldSchema>(`/projects/${projectId}/field-schemas/from-candidates`, {
      method: 'POST',
      body: json(payload),
    }),
  fieldSchemas: (projectId: string) =>
    request<FieldSchema[]>(`/projects/${projectId}/field-schemas`),
  fieldSchema: (projectId: string, schemaId: string) =>
    request<FieldSchema>(`/projects/${projectId}/field-schemas/${schemaId}`),
  createFieldSchema: (
    projectId: string,
    payload: { name: string; source_search_run_id?: string | null; fields: FieldDefinition[]; settings: Record<string, unknown> },
  ) =>
    request<FieldSchema>(`/projects/${projectId}/field-schemas`, {
      method: 'POST',
      body: json(payload),
    }),
  updateFieldSchema: (
    projectId: string,
    schemaId: string,
    payload: { name: string; source_search_run_id?: string | null; fields: FieldDefinition[]; settings: Record<string, unknown> },
  ) =>
    request<FieldSchema>(`/projects/${projectId}/field-schemas/${schemaId}`, {
      method: 'PATCH',
      body: json(payload),
    }),
  freezeFieldSchema: (projectId: string, schemaId: string) =>
    request<FieldSchema>(`/projects/${projectId}/field-schemas/${schemaId}/freeze`, {
      method: 'POST',
    }),
  units: () => request<UnitItem[]>('/units'),
  extractions: (projectId: string) =>
    request<ExtractionRun[]>(`/projects/${projectId}/extraction-runs`),
  createExtraction: (projectId: string, fieldSchemaId: string, searchRunId?: string) =>
    request<TaskAccepted>(`/projects/${projectId}/extraction-runs`, {
      method: 'POST',
      body: json({
        name: '智能抽取',
        field_schema_id: fieldSchemaId,
        search_run_id: searchRunId || null,
      }),
    }),
  extractionRecords: (
    projectId: string,
    runId: string,
    filters: { field_definition_id?: string; document_version_id?: string; review_status?: string } = {},
  ) => {
    const params = new URLSearchParams({ limit: '500' })
    Object.entries(filters).forEach(([key, value]) => value && params.set(key, value))
    return request<ListResponse<ExtractionRecord>>(
      `/projects/${projectId}/extraction-runs/${runId}/records?${params}`,
    )
  },
  extractionSummary: (projectId: string, runId: string) =>
    request<{
      extraction_run_id: string
      status: string
      total_records: number
      field_count: number
      document_count: number
      review_status_counts: Record<string, number>
    }>(`/projects/${projectId}/extraction-runs/${runId}/summary`),
  extractionQualityReport: (projectId: string, runId: string) =>
    request<QualityReport>(
      `/projects/${projectId}/extraction-runs/${runId}/quality-report`,
    ),
  reviewExtractionRecord: (
    projectId: string,
    runId: string,
    recordId: string,
    payload: {
      review_status: ExtractionRecord['review_status']
      normalized_value?: Record<string, unknown>
      ml_value?: Record<string, unknown>
      notes?: string
    },
  ) =>
    request<ExtractionRecord>(
      `/projects/${projectId}/extraction-runs/${runId}/records/${recordId}`,
      { method: 'PATCH', body: json(payload) },
    ),
  datasets: (projectId: string) =>
    request<DatasetSummary[]>(`/projects/${projectId}/datasets`),
  createDataset: (projectId: string, name: string, extractionRunId: string) =>
    request<TaskAccepted>(`/projects/${projectId}/datasets/from-extraction`, {
      method: 'POST',
      body: json({ name, extraction_run_id: extractionRunId }),
    }),
  datasetVersions: (projectId: string, datasetId: string) =>
    request<Array<DatasetVersionDetail['version']>>(
      `/projects/${projectId}/datasets/${datasetId}/versions`,
    ),
  datasetVersion: (projectId: string, versionId: string) =>
    request<DatasetVersionDetail>(
      `/projects/${projectId}/dataset-versions/${versionId}?offset=0&limit=1000`,
    ),
  addDatasetField: (
    projectId: string,
    versionId: string,
    payload: Omit<DatasetField, 'id' | 'position'>,
  ) =>
    request<DatasetField>(`/projects/${projectId}/dataset-versions/${versionId}/fields`, {
      method: 'POST',
      body: json(payload),
    }),
  addDatasetRow: (projectId: string, versionId: string, rowKey: string) =>
    request<GenericRecord>(`/projects/${projectId}/dataset-versions/${versionId}/rows`, {
      method: 'POST',
      body: json({ row_key: rowKey, metadata: {} }),
    }),
  updateDatasetCell: (
    projectId: string,
    versionId: string,
    rowId: string,
    fieldId: string,
    payload: Partial<DatasetCell>,
  ) =>
    request<DatasetCell>(
      `/projects/${projectId}/dataset-versions/${versionId}/rows/${rowId}/cells/${fieldId}`,
      { method: 'PATCH', body: json(payload) },
    ),
  deleteDatasetRow: (projectId: string, versionId: string, rowId: string) =>
    request<void>(`/projects/${projectId}/dataset-versions/${versionId}/rows/${rowId}`, {
      method: 'DELETE',
    }),
  freezeDataset: (projectId: string, versionId: string) =>
    request<DatasetVersionDetail['version']>(
      `/projects/${projectId}/dataset-versions/${versionId}/freeze`,
      { method: 'POST' },
    ),
  cloneDataset: (projectId: string, versionId: string, changeSummary: string) =>
    request<{ version_id: string; version_no: number; status: string }>(
      `/projects/${projectId}/dataset-versions/${versionId}/clone`,
      { method: 'POST', body: json({ change_summary: changeSummary }) },
    ),
  downloadDataset: (projectId: string, versionId: string, name: string) =>
    downloadBlob(
      `/projects/${projectId}/dataset-versions/${versionId}/export.xlsx`,
      `${name || 'dataset'}.xlsx`,
    ),
  derivedFeatureCandidates: (projectId: string, datasetVersionId: string) =>
    request<{ key: string; label: string; op: string; operands: string[] }[]>(
      `/projects/${projectId}/dataset-versions/${datasetVersionId}/derived-feature-candidates`,
    ),
  mlRuns: (projectId: string) =>
    request<MLRun[]>(`/projects/${projectId}/ml-runs`),
  mlRun: (projectId: string, runId: string) =>
    request<MLRun>(`/projects/${projectId}/ml-runs/${runId}`),
  createMlRun: (
    projectId: string,
    payload: {
      name: string
      dataset_version_id: string
      task_type: 'regression' | 'classification'
      input_field_ids: string[]
      target_field_id?: string
      targets?: { field_id: string; direction: 'maximize' | 'minimize'; weight: number }[]
      derived_features?: { key: string; label?: string; op: string; operands: string[] }[]
      algorithms: string[]
      random_seed: number
      test_size: number
      numeric_imputer: string
      scaler: string
      cv_folds: number
      min_samples?: number
      parameter_search: boolean
      explain: boolean
      split_strategy?: string
      cv_strategy?: string
    },
  ) =>
    request<TaskAccepted>(`/projects/${projectId}/ml-runs`, {
      method: 'POST',
      body: json(payload),
    }),
  selectMlModel: (projectId: string, runId: string, modelId: string) =>
    request<Record<string, unknown>>(
      `/projects/${projectId}/ml-runs/${runId}/models/${modelId}/select`,
      { method: 'POST' },
    ),
  predict: (projectId: string, modelId: string, values: Record<string, unknown>) =>
    request<PredictionResult>(`/projects/${projectId}/ml-models/${modelId}/predict`, {
      method: 'POST',
      body: json({ values }),
    }),
  predictMany: (projectId: string, modelIds: string[], values: Record<string, unknown>) =>
    request<{ predictions: PredictionResult[]; count: number }>(
      `/projects/${projectId}/ml-models/predict-many`,
      { method: 'POST', body: json({ model_ids: modelIds, values }) },
    ),
  optimizationRuns: (projectId: string) =>
    request<OptimizationRun[]>(`/projects/${projectId}/optimization-runs`),
  optimization: (projectId: string, runId: string) =>
    request<OptimizationRun>(`/projects/${projectId}/optimization-runs/${runId}`),
  createOptimization: (
    projectId: string,
    payload: {
      name: string
      ml_model_id: string
      ml_model_ids?: string[]
      method?: 'random_search' | 'grid_search'
      objective: Record<string, unknown>
      constraints: Record<string, Record<string, unknown>>
      grid_points?: number
      sample_count: number
      top_n: number
      random_seed: number
    },
  ) =>
    request<TaskAccepted>(`/projects/${projectId}/optimization-runs`, {
      method: 'POST',
      body: json(payload),
    }),
  optimizationExportUrl: (projectId: string, runId: string) =>
    `/api/v1/projects/${projectId}/optimization-runs/${runId}/export`,
  reports: (projectId: string) =>
    request<ReportItem[]>(`/projects/${projectId}/reports`),
  createReport: (
    projectId: string,
    title: string,
    datasetVersionId: string,
    mlRunId?: string,
    optimizationRunId?: string,
  ) =>
    request<TaskAccepted>(`/projects/${projectId}/reports`, {
      method: 'POST',
      body: json({
        title,
        dataset_version_id: datasetVersionId,
        ml_run_id: mlRunId || null,
        optimization_run_id: optimizationRunId || null,
      }),
    }),
  report: (projectId: string, reportId: string) =>
    request<ReportItem>(`/projects/${projectId}/reports/${reportId}`),
  reportLineage: (projectId: string, reportId: string) =>
    request<ReportLineage>(`/projects/${projectId}/reports/${reportId}/lineage`),
  downloadReport: async (projectId: string, reportId: string, title: string) => {
    const headers = new Headers()
    const token = session.getToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
    const response = await fetch(
      `${API_PREFIX}/projects/${projectId}/reports/${reportId}/download`,
      { headers },
    )
    if (!response.ok) {
      throw new ApiError(response.status, 'download_failed', '报告下载失败')
    }
    const blobUrl = URL.createObjectURL(await response.blob())
    const anchor = document.createElement('a')
    anchor.href = blobUrl
    anchor.download = `${title || 'research-report'}.docx`
    anchor.click()
    URL.revokeObjectURL(blobUrl)
  },
  prisma: (projectId: string) =>
    request<PrismaFlow>(`/projects/${projectId}/prisma`),
  updatePrisma: (
    projectId: string,
    payload: PrismaFlowData & { notes?: string | null },
  ) =>
    request<PrismaFlow>(`/projects/${projectId}/prisma`, {
      method: 'PUT',
      body: json(payload),
    }),
  auditLogs: (projectId: string) =>
    request<ListResponse<GenericRecord>>(`/projects/${projectId}/audit-logs?limit=100`),
}

