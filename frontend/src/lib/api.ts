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
  created_at: string
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
  terms: (projectId: string) =>
    request<ListResponse<GenericRecord>>(`/projects/${projectId}/terms?limit=200`),
  fieldSchemas: (projectId: string) =>
    request<GenericRecord[]>(`/projects/${projectId}/field-schemas`),
  extractions: (projectId: string) =>
    request<GenericRecord[]>(`/projects/${projectId}/extraction-runs`),
  createExtraction: (projectId: string, fieldSchemaId: string, searchRunId?: string) =>
    request<TaskAccepted>(`/projects/${projectId}/extraction-runs`, {
      method: 'POST',
      body: json({
        name: '智能抽取',
        field_schema_id: fieldSchemaId,
        search_run_id: searchRunId || null,
      }),
    }),
  datasets: (projectId: string) =>
    request<GenericRecord[]>(`/projects/${projectId}/datasets`),
  createDataset: (projectId: string, name: string, extractionRunId: string) =>
    request<TaskAccepted>(`/projects/${projectId}/datasets/from-extraction`, {
      method: 'POST',
      body: json({ name, extraction_run_id: extractionRunId }),
    }),
  mlRuns: (projectId: string) =>
    request<GenericRecord[]>(`/projects/${projectId}/ml-runs`),
  optimization: (projectId: string, runId: string) =>
    request<GenericRecord>(`/projects/${projectId}/optimization-runs/${runId}`),
  reports: (projectId: string) =>
    request<GenericRecord[]>(`/projects/${projectId}/reports`),
  createReport: (
    projectId: string,
    title: string,
    datasetVersionId: string,
    mlRunId?: string,
  ) =>
    request<TaskAccepted>(`/projects/${projectId}/reports`, {
      method: 'POST',
      body: json({
        title,
        dataset_version_id: datasetVersionId,
        ml_run_id: mlRunId || null,
      }),
    }),
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
  auditLogs: (projectId: string) =>
    request<ListResponse<GenericRecord>>(`/projects/${projectId}/audit-logs?limit=100`),
}

