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
    request<ListResponse<GenericRecord>>(`/projects/${projectId}/search-runs?limit=100`),
  createSearch: (projectId: string, terms: string[], name?: string) =>
    request<TaskAccepted>(`/projects/${projectId}/search-runs`, {
      method: 'POST',
      body: json({ name, terms, logic_operator: 'AND', search_mode: 'hybrid' }),
    }),
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

