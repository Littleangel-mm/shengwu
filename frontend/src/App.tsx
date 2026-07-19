import {
  Activity,
  ArrowLeft,
  ArrowRight,
  Atom,
  BarChart3,
  BookOpen,
  BrainCircuit,
  ChevronRight,
  CircleCheck,
  Database,
  Download,
  FileSearch,
  FileText,
  FlaskConical,
  FolderKanban,
  Gem,
  Image,
  Layers3,
  Languages,
  LoaderCircle,
  LockKeyhole,
  LogOut,
  Menu,
  Network,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Sparkles,
  Table2,
  Upload,
  UserRound,
  X,
} from 'lucide-react'
import { AnimatePresence, motion } from 'framer-motion'
import {
  createContext,
  type FormEvent,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useState,
} from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  Link,
  Navigate,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
} from 'react-router-dom'
import {
  api,
  type GenericRecord,
  type JobItem,
  type Project,
  type SearchMode,
  type SearchRun,
  type SearchScope,
  session,
  type User,
} from './lib/api'

type AuthState = {
  user: User | null
  loading: boolean
  authenticate: (token: string, user: User) => void
  logout: () => void
}

const AuthContext = createContext<AuthState | null>(null)

function useAuth() {
  const value = useContext(AuthContext)
  if (!value) throw new Error('AuthContext is unavailable')
  return value
}

function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null)
  const [loading, setLoading] = useState(Boolean(session.getToken()))

  useEffect(() => {
    if (!session.getToken()) {
      setLoading(false)
      return
    }
    api
      .me()
      .then(setUser)
      .catch(() => session.clear())
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    const onUnauthorized = () => {
      session.clear()
      setUser(null)
    }
    window.addEventListener('shengwu:unauthorized', onUnauthorized)
    return () => window.removeEventListener('shengwu:unauthorized', onUnauthorized)
  }, [])

  const value = useMemo<AuthState>(
    () => ({
      user,
      loading,
      authenticate: (token, nextUser) => {
        session.setToken(token)
        setUser(nextUser)
      },
      logout: () => {
        session.clear()
        setUser(null)
      },
    }),
    [loading, user],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

function Brand({ compact = false }: { compact?: boolean }) {
  return (
    <Link to="/" className={`brand ${compact ? 'brand-compact' : ''}`} aria-label="溯研首页">
      <span className="brand-mark">
        <Atom size={20} />
      </span>
      <span>
        <strong>溯研</strong>
        {!compact && <small>科研智能平台</small>}
      </span>
    </Link>
  )
}

function StatusPill({ value }: { value: unknown }) {
  const text = String(value || 'unknown')
  const labels: Record<string, string> = {
    ready: '就绪',
    active: '正常',
    completed: '已完成',
    confirmed: '已确认',
    frozen: '已冻结',
    queued: '排队中',
    running: '运行中',
    processing: '处理中',
    pending: '待处理',
    draft: '草稿',
    failed: '失败',
    partial: '部分完成',
    unknown: '未知',
  }
  const positive = ['ready', 'active', 'completed', 'confirmed', 'frozen'].includes(text)
  const pending = ['queued', 'running', 'processing', 'pending', 'draft'].includes(text)
  return (
    <span className={`status-pill ${positive ? 'positive' : pending ? 'pending' : 'neutral'}`}>
      <span />
      {labels[text] || text}
    </span>
  )
}

function ErrorNotice({ error }: { error: unknown }) {
  if (!error) return null
  const message = error instanceof Error ? error.message : '请求失败，请稍后重试'
  return <div className="error-notice">{message}</div>
}

function LoadingPane({ label = '正在同步研究数据' }: { label?: string }) {
  return (
    <div className="loading-pane">
      <LoaderCircle className="spin" />
      <span>{label}</span>
    </div>
  )
}

function LandingPage() {
  const { user } = useAuth()
  const capabilities = [
    { icon: FileSearch, label: '文献智能解析', text: '多格式解析、OCR 与证据坐标' },
    { icon: Network, label: '证据关系网络', text: '术语、字段、原文证据完整关联' },
    { icon: Database, label: '可信数据集', text: '版本冻结与可验证数据资产' },
    { icon: BrainCircuit, label: '智能建模实验室', text: '模型训练、预测和方案优化' },
  ]
  const values = [
    ['01', '精准', '每个结论都来自可定位的原始证据。'],
    ['02', '可追溯', '从报告一键回溯文献、页码与数据单元。'],
    ['03', '隐私安全', '租户隔离、角色权限与完整审计。'],
    ['04', '可复现', '冻结版本、模型哈希与环境快照。'],
  ]

  return (
    <main className="landing">
      <div className="ambient ambient-one" />
      <div className="ambient ambient-two" />
      <nav className="landing-nav glass">
        <Brand />
        <div className="nav-links">
          <a href="#platform">平台</a>
          <a href="#workflow">工作流</a>
          <a href="#values">品牌价值</a>
        </div>
        <Link className="button button-ghost" to={user ? '/app' : '/auth'}>
          {user ? '进入工作台' : '登录'}
          <ArrowRight size={16} />
        </Link>
      </nav>

      <section className="hero-section">
        <motion.div
          className="hero-copy"
          initial={{ opacity: 0, y: 28 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.8 }}
        >
          <span className="eyebrow">
            <Sparkles size={14} /> 专属科研智能空间
          </span>
          <h1>
            从科研文献
            <br />
            到<em>智能洞察</em>
          </h1>
          <p>
            将散落于文献中的证据，转化为可验证、可建模、可决策的高价值数据资产。
          </p>
          <div className="hero-actions">
            <Link className="button button-primary" to={user ? '/app' : '/auth?mode=register'}>
              开启研究空间 <ArrowRight size={17} />
            </Link>
            <a className="button button-text" href="#workflow">
              探索工作流 <ChevronRight size={17} />
            </a>
          </div>
          <div className="trust-row">
            <span>
              <ShieldCheck size={16} /> 租户数据隔离
            </span>
            <span>
              <LockKeyhole size={16} /> 证据安全保护
            </span>
            <span>
              <CircleCheck size={16} /> 模型完整验证
            </span>
          </div>
        </motion.div>

        <motion.div
          className="hero-visual"
          initial={{ opacity: 0, scale: 0.92 }}
          animate={{ opacity: 1, scale: 1 }}
          transition={{ duration: 1, delay: 0.12 }}
        >
          <div className="orbital-ring ring-one" />
          <div className="orbital-ring ring-two" />
          <div className="hero-card main-card glass">
            <div className="card-topline">
              <span>研究可信信号</span>
              <StatusPill value="ready" />
            </div>
            <div className="signal-value">94.8%</div>
            <p>证据可信度</p>
            <div className="mini-chart">
              {[28, 46, 36, 68, 57, 84, 72, 96].map((height, index) => (
                <i key={index} style={{ height: `${height}%` }} />
              ))}
            </div>
          </div>
          <div className="hero-card floating-card card-document glass">
            <FileText size={19} />
            <span>
              <strong>128</strong>
              <small>已解析文献</small>
            </span>
          </div>
          <div className="hero-card floating-card card-model glass">
            <BrainCircuit size={19} />
            <span>
              <strong>R² 0.91</strong>
              <small>已选模型</small>
            </span>
          </div>
          <div className="hero-card floating-card card-trace glass">
            <Gem size={19} />
            <span>
              <strong>已验证</strong>
              <small>证据追溯链</small>
            </span>
          </div>
        </motion.div>
      </section>

      <section id="platform" className="section-block">
        <div className="section-heading">
          <span className="eyebrow">平台能力</span>
          <h2>复杂科研流程，凝练为一套优雅系统。</h2>
        </div>
        <div className="capability-grid">
          {capabilities.map(({ icon: Icon, label, text }, index) => (
            <motion.article
              className="capability-card glass"
              key={label}
              initial={{ opacity: 0, y: 20 }}
              whileInView={{ opacity: 1, y: 0 }}
              viewport={{ once: true }}
              transition={{ delay: index * 0.08 }}
            >
              <span className="icon-box">
                <Icon size={21} />
              </span>
              <small>0{index + 1}</small>
              <h3>{label}</h3>
              <p>{text}</p>
            </motion.article>
          ))}
        </div>
      </section>

      <section id="workflow" className="story-section section-block">
        <div className="story-copy">
          <span className="eyebrow">连续科研工作流</span>
          <h2>从第一篇文献，到最终决策。</h2>
          <p>
            每一步都保留上下文、版本与证据。系统不会让智能分析成为无法解释的黑箱。
          </p>
        </div>
        <div className="story-flow glass">
          {['科研文献', '原始证据', '可信数据集', '智能分析', '研究决策'].map(
            (item, index) => (
              <div className="story-step" key={item}>
                <span>{String(index + 1).padStart(2, '0')}</span>
                <strong>{item}</strong>
                {index < 4 && <ArrowRight size={16} />}
              </div>
            ),
          )}
        </div>
      </section>

      <section id="values" className="values-section section-block">
        <div className="section-heading">
          <span className="eyebrow">平台标准</span>
          <h2>真正的高级感，来自对细节的绝对掌控。</h2>
        </div>
        <div className="values-list">
          {values.map(([number, title, text]) => (
            <div className="value-row" key={number}>
              <span>{number}</span>
              <h3>{title}</h3>
              <p>{text}</p>
              <ChevronRight />
            </div>
          ))}
        </div>
      </section>

      <section className="membership section-block glass">
        <div>
          <span className="eyebrow">专属研究空间</span>
          <h2>进入属于你的专属研究空间。</h2>
          <p>让证据、数据与模型在同一个可信环境中持续进化。</p>
        </div>
        <Link className="button button-primary" to={user ? '/app' : '/auth?mode=register'}>
          进入研究空间 <ArrowRight size={17} />
        </Link>
      </section>

      <footer>
        <Brand />
        <span>© 2026 溯研科研智能平台 · 为可信证据而生</span>
      </footer>
    </main>
  )
}

function AuthPage() {
  const location = useLocation()
  const navigate = useNavigate()
  const { user, authenticate } = useAuth()
  const initialMode = new URLSearchParams(location.search).get('mode')
  const [mode, setMode] = useState<'login' | 'register'>(
    initialMode === 'register' ? 'register' : 'login',
  )
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [submitting, setSubmitting] = useState(false)

  if (user) return <Navigate to="/app" replace />

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      const result =
        mode === 'login'
          ? await api.login(email, password)
          : await api.register(email, displayName, password)
      authenticate(result.access_token, result.user)
      navigate('/app')
    } catch (nextError) {
      setError(nextError)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <main className="auth-page">
      <div className="auth-art">
        <Link to="/">
          <Brand />
        </Link>
        <div className="auth-quote">
          <span className="eyebrow">隐私优先设计</span>
          <h1>让每一条科研证据，都拥有清晰归宿。</h1>
          <p>证据安全可靠，研究结果可复现。</p>
        </div>
        <div className="auth-orbit">
          <Atom />
        </div>
      </div>
      <section className="auth-panel">
        <div className="auth-card">
          <span className="eyebrow">{mode === 'login' ? '欢迎回来' : '创建专属账户'}</span>
          <h2>{mode === 'login' ? '回到研究现场' : '创建专属研究空间'}</h2>
          <p>{mode === 'login' ? '继续你的证据与数据工作流。' : '用结构化智能开启下一项研究。'}</p>
          <form onSubmit={submit}>
            {mode === 'register' && (
              <label>
                <span>姓名</span>
                <input
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  required
                  placeholder="请输入姓名"
                />
              </label>
            )}
            <label>
              <span>邮箱</span>
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
                placeholder="请输入邮箱地址"
              />
            </label>
            <label>
              <span>密码</span>
              <input
                type="password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={mode === 'register' ? 10 : undefined}
                required
                placeholder="••••••••••"
              />
            </label>
            <ErrorNotice error={error} />
            <button className="button button-primary button-wide" disabled={submitting}>
              {submitting && <LoaderCircle className="spin" size={17} />}
              {mode === 'login' ? '安全登录' : '创建账户'}
              {!submitting && <ArrowRight size={17} />}
            </button>
          </form>
          <button
            className="auth-switch"
            onClick={() => {
              setMode(mode === 'login' ? 'register' : 'login')
              setError(null)
            }}
          >
            {mode === 'login' ? '尚未拥有账户？申请访问' : '已有账户？返回登录'}
          </button>
        </div>
      </section>
    </main>
  )
}

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <LoadingPane label="正在验证安全会话" />
  if (!user) return <Navigate to="/auth" replace />
  return children
}

function AppHeader({ title }: { title: string }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const health = useQuery({
    queryKey: ['api-health'],
    queryFn: api.health,
    refetchInterval: 30_000,
    retry: false,
  })
  return (
    <header className="app-header">
      <div>
        <span className="breadcrumb">专属科研工作空间</span>
        <h1>{title}</h1>
      </div>
      <div className="header-actions">
        <div className={`health-chip ${health.isError ? 'down' : ''}`}>
          <span />
          {health.isError ? '接口不可用' : health.isLoading ? '正在检查接口' : '接口已连接'}
        </div>
        <div className="user-chip">
          <span className="avatar">
            <UserRound size={16} />
          </span>
          <span>
            <strong>{user?.display_name}</strong>
            <small>{user?.email}</small>
          </span>
        </div>
        <button
          className="icon-button"
          title="退出登录"
          onClick={() => {
            logout()
            navigate('/')
          }}
        >
          <LogOut size={18} />
        </button>
      </div>
    </header>
  )
}

function DashboardPage() {
  const queryClient = useQueryClient()
  const [showCreate, setShowCreate] = useState<'project' | 'organization' | null>(null)
  const [selectedOrg, setSelectedOrg] = useState('')
  const [name, setName] = useState('')
  const [domain, setDomain] = useState('')
  const organizations = useQuery({
    queryKey: ['organizations'],
    queryFn: api.organizations,
  })
  const projects = useQuery({ queryKey: ['projects'], queryFn: () => api.projects() })
  const createOrganization = useMutation({
    mutationFn: () => api.createOrganization(name),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['organizations'] })
      setShowCreate(null)
      setName('')
    },
  })
  const createProject = useMutation({
    mutationFn: () =>
      api.createProject({
        organization_id: selectedOrg,
        name,
        research_domain: domain || undefined,
      }),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['projects'] })
      setShowCreate(null)
      setName('')
      setDomain('')
    },
  })

  const orgItems = organizations.data?.items || []
  const projectItems = projects.data?.items || []

  return (
    <div className="app-page">
      <AppHeader title="研究项目总览" />
      <section className="dashboard-content">
        <div className="dashboard-intro">
          <div>
            <span className="eyebrow">我的研究项目</span>
            <h2>所有研究项目，一个可信入口。</h2>
            <p>继续文献解析、证据审核或模型实验。</p>
          </div>
          <div className="button-row">
            <button className="button button-ghost" onClick={() => setShowCreate('organization')}>
              <Plus size={16} /> 新建组织
            </button>
            <button className="button button-primary" onClick={() => setShowCreate('project')}>
              <Plus size={16} /> 新建项目
            </button>
          </div>
        </div>

        {(organizations.isLoading || projects.isLoading) && <LoadingPane />}
        <ErrorNotice error={organizations.error || projects.error} />

        {!projects.isLoading && projectItems.length === 0 && (
          <div className="empty-state glass">
            <FolderKanban size={32} />
            <h3>创建你的第一项研究</h3>
            <p>先创建组织，再建立一个专属项目空间。</p>
            <button
              className="button button-primary"
              onClick={() => setShowCreate(orgItems.length ? 'project' : 'organization')}
            >
              开始创建 <ArrowRight size={16} />
            </button>
          </div>
        )}

        <div className="project-grid">
          {projectItems.map((project, index) => (
            <motion.div
              key={project.id}
              initial={{ opacity: 0, y: 18 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: index * 0.06 }}
            >
              <Link className="project-card glass" to={`/app/projects/${project.id}/overview`}>
                <div className="project-card-top">
                  <span className="project-symbol">
                    <FlaskConical size={20} />
                  </span>
                  <StatusPill value={project.status} />
                </div>
                <div>
                  <small>{project.research_domain || '综合研究'}</small>
                  <h3>{project.name}</h3>
                  <p>{project.description || '等待你导入第一批研究文献。'}</p>
                </div>
                <div className="project-card-footer">
                  <span>{new Date(project.created_at).toLocaleDateString('zh-CN')}</span>
                  <span>
                    打开工作台 <ArrowRight size={15} />
                  </span>
                </div>
              </Link>
            </motion.div>
          ))}
        </div>
      </section>

      <AnimatePresence>
        {showCreate && (
          <motion.div
            className="modal-backdrop"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <motion.div
              className="modal glass"
              initial={{ opacity: 0, scale: 0.96, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.96 }}
            >
              <button className="modal-close" onClick={() => setShowCreate(null)}>
                <X size={18} />
              </button>
              <span className="eyebrow">{showCreate === 'project' ? '新建项目' : '新建组织'}</span>
              <h2>{showCreate === 'project' ? '创建研究项目' : '创建研究组织'}</h2>
              <form
                onSubmit={(event) => {
                  event.preventDefault()
                  if (showCreate === 'organization') createOrganization.mutate()
                  else createProject.mutate()
                }}
              >
                {showCreate === 'project' && (
                  <label>
                    <span>所属组织</span>
                    <select
                      value={selectedOrg}
                      onChange={(event) => setSelectedOrg(event.target.value)}
                      required
                    >
                      <option value="">选择组织</option>
                      {orgItems.map((item) => (
                        <option key={item.id} value={item.id}>
                          {item.name}
                        </option>
                      ))}
                    </select>
                  </label>
                )}
                <label>
                  <span>{showCreate === 'project' ? '项目名称' : '组织名称'}</span>
                  <input value={name} onChange={(event) => setName(event.target.value)} required />
                </label>
                {showCreate === 'project' && (
                  <label>
                    <span>研究领域</span>
                    <input
                      value={domain}
                      onChange={(event) => setDomain(event.target.value)}
                      placeholder="例如：生物发酵"
                    />
                  </label>
                )}
                <ErrorNotice error={createProject.error || createOrganization.error} />
                <button
                  className="button button-primary button-wide"
                  disabled={createProject.isPending || createOrganization.isPending}
                >
                  确认创建 <ArrowRight size={16} />
                </button>
              </form>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}

const workspaceNav = [
  { key: 'overview', label: '项目概览', icon: Layers3 },
  { key: 'documents', label: '文献管理', icon: BookOpen },
  { key: 'search', label: '证据检索', icon: Search },
  { key: 'terms', label: '术语与字段', icon: Network },
  { key: 'extraction', label: '数据抽取', icon: FileSearch },
  { key: 'datasets', label: '数据集', icon: Database },
  { key: 'models', label: '模型实验', icon: BrainCircuit },
  { key: 'reports', label: '研究报告', icon: BarChart3 },
  { key: 'audit', label: '审计记录', icon: ShieldCheck },
]

function WorkspacePage() {
  const { projectId = '', section = 'overview', documentId } = useParams()
  const [mobileNav, setMobileNav] = useState(false)
  const project = useQuery({
    queryKey: ['project', projectId],
    queryFn: () => api.project(projectId),
    enabled: Boolean(projectId),
  })

  return (
    <div className="workspace">
      <aside className={`workspace-sidebar ${mobileNav ? 'open' : ''}`}>
        <div className="sidebar-brand">
          <Brand />
          <button className="mobile-close" onClick={() => setMobileNav(false)}>
            <X />
          </button>
        </div>
        <div className="project-identity">
          <span className="project-symbol">
            <FlaskConical size={19} />
          </span>
          <span>
            <small>当前研究项目</small>
            <strong>{project.data?.name || '加载中…'}</strong>
          </span>
        </div>
        <nav className="workspace-nav">
          {workspaceNav.map(({ key, label, icon: Icon }) => (
            <NavLink
              key={key}
              to={`/app/projects/${projectId}/${key}`}
              onClick={() => setMobileNav(false)}
              className={({ isActive }) => (isActive ? 'active' : '')}
            >
              <Icon size={17} />
              <span>{label}</span>
              <ChevronRight size={14} />
            </NavLink>
          ))}
        </nav>
        <Link className="back-portfolio" to="/app">
          <FolderKanban size={16} /> 全部项目
        </Link>
      </aside>
      <main className="workspace-main">
        <button className="mobile-menu" onClick={() => setMobileNav(true)}>
          <Menu size={20} />
        </button>
        <AppHeader
          title={
            documentId
              ? '文献详情'
              : workspaceNav.find((item) => item.key === section)?.label || '项目概览'
          }
        />
        {documentId ? (
          <DocumentDetailSection projectId={projectId} documentId={documentId} />
        ) : (
          <WorkspaceSection projectId={projectId} section={section} project={project.data} />
        )}
      </main>
    </div>
  )
}

function WorkspaceSection({
  projectId,
  section,
  project,
}: {
  projectId: string
  section: string
  project?: Project
}) {
  if (section === 'overview') return <OverviewSection projectId={projectId} project={project} />
  if (section === 'documents') return <DocumentsSection projectId={projectId} />
  if (section === 'search') return <SearchSection projectId={projectId} />
  if (section === 'terms')
    return (
      <RecordsSection
        title="术语与字段方案"
        eyebrow="统一研究语言"
        description="审核术语、别名和字段方案，建立统一研究语言。"
        queryKey={['terms', projectId]}
        queryFn={() => api.terms(projectId)}
        unwrap={(data) => (data as Awaited<ReturnType<typeof api.terms>>).items}
      />
    )
  if (section === 'extraction') return <ExtractionSection projectId={projectId} />
  if (section === 'datasets') return <DatasetsSection projectId={projectId} />
  if (section === 'models')
    return (
      <RecordsSection
        title="智能建模实验室"
        eyebrow="预测与优化"
        description="比较训练运行、模型指标与优化结果。"
        queryKey={['ml-runs', projectId]}
        queryFn={() => api.mlRuns(projectId)}
      />
    )
  if (section === 'reports') return <ReportsSection projectId={projectId} />
  if (section === 'audit')
    return (
      <RecordsSection
        title="审计记录"
        eyebrow="可验证历史"
        description="追踪项目中的关键变更与安全事件。"
        queryKey={['audit', projectId]}
        queryFn={() => api.auditLogs(projectId)}
        unwrap={(data) => (data as Awaited<ReturnType<typeof api.auditLogs>>).items}
      />
    )
  return <Navigate to={`/app/projects/${projectId}/overview`} replace />
}

function OverviewSection({ projectId, project }: { projectId: string; project?: Project }) {
  const documents = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => api.documents(projectId),
  })
  const jobs = useQuery({
    queryKey: ['jobs', projectId],
    queryFn: () => api.jobs(projectId),
    refetchInterval: 5_000,
  })
  const datasets = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () => api.datasets(projectId),
  })
  const models = useQuery({ queryKey: ['ml-runs', projectId], queryFn: () => api.mlRuns(projectId) })
  const recentJobs = jobs.data?.items.slice(0, 5) || []

  return (
    <div className="workspace-content">
      <div className="workspace-hero glass">
        <div>
          <span className="eyebrow">项目智能概览</span>
          <h2>{project?.name || '科研项目'}</h2>
          <p>{project?.description || '从文献证据开始构建可信研究资产。'}</p>
        </div>
        <Link className="button button-primary" to={`/app/projects/${projectId}/documents`}>
          <Upload size={16} /> 导入文献
        </Link>
      </div>
      <div className="metric-grid">
        <MetricCard
          icon={BookOpen}
          label="文献数量"
          value={documents.data?.total ?? '—'}
          hint="研究来源"
        />
        <MetricCard
          icon={Activity}
          label="进行中任务"
          value={jobs.data?.items.filter((job) => ['queued', 'running'].includes(job.status)).length ?? '—'}
          hint="后台任务"
        />
        <MetricCard icon={Database} label="数据集" value={datasets.data?.length ?? '—'} hint="数据资产" />
        <MetricCard icon={BrainCircuit} label="模型运行" value={models.data?.length ?? '—'} hint="智能实验" />
      </div>
      <div className="content-grid">
        <section className="panel glass span-two">
          <PanelHeading eyebrow="实时任务" title="最近处理进度" />
          {jobs.isLoading ? (
            <LoadingPane />
          ) : recentJobs.length ? (
            <div className="record-list compact">
              {recentJobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </div>
          ) : (
            <EmptyInline text="暂无处理任务" />
          )}
        </section>
        <section className="panel glass">
          <PanelHeading eyebrow="证据追溯" title="可信证据标准" />
          <div className="quality-score">
            <strong>100%</strong>
            <span>原文证据可追溯</span>
          </div>
          <div className="quality-line">
            <i />
          </div>
          <p className="muted">数据、模型和报告保留完整来源链。</p>
        </section>
      </div>
    </div>
  )
}

function MetricCard({
  icon: Icon,
  label,
  value,
  hint,
}: {
  icon: typeof BookOpen
  label: string
  value: string | number
  hint: string
}) {
  return (
    <div className="metric-card glass">
      <span className="metric-icon">
        <Icon size={19} />
      </span>
      <span className="metric-label">{label}</span>
      <strong>{value}</strong>
      <small>{hint}</small>
    </div>
  )
}

function PanelHeading({ eyebrow, title }: { eyebrow: string; title: string }) {
  return (
    <div className="panel-heading">
      <span>{eyebrow}</span>
      <h3>{title}</h3>
    </div>
  )
}

function EmptyInline({ text }: { text: string }) {
  return (
    <div className="empty-inline">
      <Sparkles size={19} />
      <span>{text}</span>
    </div>
  )
}

function JobRow({ job, action }: { job: JobItem; action?: ReactNode }) {
  const jobNames: Record<string, string> = {
    parse_document: '解析文献',
    execute_search: '执行证据检索',
    translate_document: '翻译文献',
    discover_terms: '发现候选术语',
    run_extraction: '抽取结构化数据',
    build_dataset: '构建数据集',
    train_model: '训练模型',
    run_optimization: '运行方案优化',
    generate_report: '生成研究报告',
  }
  return (
    <div className="record-row">
      <span className="record-icon">
        <Activity size={17} />
      </span>
      <div>
        <strong>{jobNames[job.job_type] || job.job_type}</strong>
        <small>{job.current_stage || new Date(job.queued_at).toLocaleString('zh-CN')}</small>
      </div>
      <div className="record-progress">
        <i style={{ width: `${Number(job.progress_percent || 0)}%` }} />
      </div>
      <StatusPill value={job.status} />
      {action}
    </div>
  )
}

function TaskLogModal({
  projectId,
  job,
  onClose,
}: {
  projectId: string
  job: JobItem
  onClose: () => void
}) {
  const events = useQuery({
    queryKey: ['job-events', projectId, job.id],
    queryFn: () => api.jobEvents(projectId, job.id),
    refetchInterval: ['queued', 'running'].includes(job.status) ? 3_000 : false,
  })
  const estimates: Record<string, string> = {
    parse_document: '普通文献约 10 秒至 2 分钟；扫描件通常每 10 页约 1 至 3 分钟',
    execute_search: '通常 5 至 30 秒',
    translate_document: '通常每篇 1 至 5 分钟',
    discover_terms: '通常 10 秒至 1 分钟',
    run_extraction: '通常 30 秒至 5 分钟',
    build_dataset: '通常 10 秒至 2 分钟',
    train_model: '通常 1 至 20 分钟，取决于算法与数据规模',
    run_optimization: '通常 30 秒至 10 分钟',
    generate_report: '通常 10 秒至 2 分钟',
  }
  const stageNames: Record<string, string> = {
    waiting: '等待工作进程',
    starting: '正在启动',
    loading_document: '加载文献',
    parsing: '解析内容',
    extracting_text: '提取文本',
    extracting_tables: '提取表格',
    running_ocr: '执行文字识别',
    completed: '处理完成',
    failed: '处理失败',
  }
  const start = new Date(job.started_at || job.queued_at).getTime()
  const end = job.completed_at ? new Date(job.completed_at).getTime() : Date.now()
  const elapsedSeconds = Math.max(0, Math.floor((end - start) / 1000))
  const elapsed =
    elapsedSeconds >= 60
      ? `${Math.floor(elapsedSeconds / 60)} 分 ${elapsedSeconds % 60} 秒`
      : `${elapsedSeconds} 秒`

  return (
    <motion.div
      className="modal-backdrop"
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
    >
      <motion.section
        className="task-log-modal glass"
        initial={{ opacity: 0, y: 16, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 12 }}
      >
        <button className="modal-close" onClick={onClose}>
          <X size={18} />
        </button>
        <span className="eyebrow">任务运行详情</span>
        <div className="task-log-title">
          <div>
            <h2>{stageNames[job.current_stage || ''] || '后台处理任务'}</h2>
            <p>{estimates[job.job_type] || '处理时间取决于数据规模和机器性能'}</p>
          </div>
          <StatusPill value={job.status} />
        </div>
        <div className="task-stats">
          <div>
            <span>当前进度</span>
            <strong>{Math.round(Number(job.progress_percent || 0))}%</strong>
          </div>
          <div>
            <span>已用时间</span>
            <strong>{elapsed}</strong>
          </div>
          <div>
            <span>开始时间</span>
            <strong>
              {job.started_at ? new Date(job.started_at).toLocaleTimeString('zh-CN') : '等待中'}
            </strong>
          </div>
        </div>
        {job.error_message && <div className="error-notice">{job.error_message}</div>}
        <div className="log-console">
          <div className="log-console-head">
            <span>处理日志</span>
            {events.isFetching && <LoaderCircle className="spin" size={14} />}
          </div>
          {events.isLoading ? (
            <LoadingPane label="正在读取任务日志" />
          ) : events.data?.length ? (
            <div className="log-lines">
              {events.data.map((event) => (
                <div className={`log-line ${event.level}`} key={event.id}>
                  <time>{new Date(event.created_at).toLocaleTimeString('zh-CN')}</time>
                  <span>{Math.round(Number(event.progress_percent || 0))}%</span>
                  <p>{event.message || stageNames[event.stage || ''] || event.event_type}</p>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-inline">
              当前任务创建于日志功能启用前，暂时只有状态和进度信息。
            </div>
          )}
        </div>
      </motion.section>
    </motion.div>
  )
}

function formatFileSize(value?: number | null) {
  if (!value) return '未知大小'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / 1024 / 1024).toFixed(1)} MB`
}

function FigurePreview({
  projectId,
  documentId,
  figureId,
  alt,
}: {
  projectId: string
  documentId: string
  figureId: string
  alt: string
}) {
  const [source, setSource] = useState<string>()
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let blobUrl = ''
    let active = true
    api
      .figureBlob(projectId, documentId, figureId)
      .then((blob) => {
        if (!active) return
        blobUrl = URL.createObjectURL(blob)
        setSource(blobUrl)
      })
      .catch(() => active && setFailed(true))
    return () => {
      active = false
      if (blobUrl) URL.revokeObjectURL(blobUrl)
    }
  }, [documentId, figureId, projectId])

  if (failed) return <div className="figure-placeholder">图片文件不可用</div>
  if (!source) return <LoadingPane label="正在读取图片" />
  return <img src={source} alt={alt} />
}

function DocumentDetailSection({
  projectId,
  documentId,
}: {
  projectId: string
  documentId: string
}) {
  const queryClient = useQueryClient()
  const location = useLocation()
  const [error, setError] = useState<unknown>(null)
  const [activePage, setActivePage] = useState<number>()
  const detail = useQuery({
    queryKey: ['document', projectId, documentId],
    queryFn: () => api.documentDetail(projectId, documentId),
  })
  const reparse = useMutation({
    mutationFn: () => api.reparseDocument(projectId, documentId),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['document', projectId, documentId] }),
        queryClient.invalidateQueries({ queryKey: ['jobs', projectId] }),
      ])
    },
    onError: setError,
  })
  const translate = useMutation({
    mutationFn: (versionId: string) => api.translateDocument(projectId, versionId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs', projectId] }),
    onError: setError,
  })

  if (detail.isLoading) return <LoadingPane label="正在读取文献详情" />
  if (detail.error || !detail.data)
    return (
      <div className="workspace-content">
        <ErrorNotice error={detail.error || new Error('文献详情不存在')} />
        <Link className="button button-secondary" to={`/app/projects/${projectId}/documents`}>
          <ArrowLeft size={16} /> 返回文献库
        </Link>
      </div>
    )

  const data = {
    ...detail.data,
    pages: detail.data.pages ?? [],
    blocks: detail.data.blocks ?? [],
    tables: detail.data.tables ?? [],
    figures: detail.data.figures ?? [],
    counts: detail.data.counts ?? { blocks: 0, tables: 0, figures: 0 },
  }
  const requestedPage = Number(new URLSearchParams(location.search).get('page')) || undefined
  const selectedPage = activePage || requestedPage || data.pages[0]?.page_no
  const page = data.pages.find((item) => item.page_no === selectedPage)
  const pageBlocks = data.blocks.filter((block) => block.page_id === page?.id)
  const pageTables = data.tables.filter((table) => table.page_id === page?.id)
  const pageFigures = data.figures.filter((figure) => figure.page_id === page?.id)
  const filename = data.version.original_name || data.document.title || '研究文献'

  return (
    <div className="workspace-content document-detail">
      <div className="detail-toolbar">
        <Link className="back-link" to={`/app/projects/${projectId}/documents`}>
          <ArrowLeft size={16} /> 返回文献库
        </Link>
        <div className="detail-actions">
          <button
            className="button button-secondary"
            onClick={() => api.downloadDocument(projectId, documentId, filename).catch(setError)}
          >
            <Download size={16} /> 下载原文
          </button>
          <button
            className="button button-secondary"
            disabled={translate.isPending}
            onClick={() => translate.mutate(data.version.id)}
          >
            {translate.isPending ? <LoaderCircle className="spin" size={16} /> : <Languages size={16} />}
            翻译为中文
          </button>
          <button
            className="button button-primary"
            disabled={reparse.isPending}
            onClick={() => reparse.mutate()}
          >
            {reparse.isPending ? <LoaderCircle className="spin" size={16} /> : <Sparkles size={16} />}
            重新解析
          </button>
        </div>
      </div>
      <ErrorNotice error={error || reparse.error || translate.error} />
      <section className="document-summary glass">
        <div>
          <span className="eyebrow">文献证据详情</span>
          <h2>{data.document.title || filename}</h2>
          <p>
            {data.document.authors?.length ? data.document.authors.join('、') : '作者信息待识别'}
            {data.document.publication_name ? ` · ${data.document.publication_name}` : ''}
          </p>
        </div>
        <StatusPill value={data.version.parse_status} />
      </section>
      <div className="metric-grid document-metrics">
        <MetricCard icon={FileText} label="当前版本" value={`V${data.version.version_no}`} hint={filename} />
        <MetricCard icon={BookOpen} label="文献页数" value={data.version.page_count ?? data.pages.length} hint="解析页面" />
        <MetricCard icon={Table2} label="表格数量" value={data.counts.tables} hint={`${data.counts.blocks} 个正文块`} />
        <MetricCard icon={Image} label="图片数量" value={data.counts.figures} hint={formatFileSize(data.version.byte_size)} />
      </div>
      {data.pages.length ? (
        <div className="evidence-layout">
          <aside className="page-index glass">
            <PanelHeading eyebrow="文献目录" title="页面" />
            <div className="page-index-list">
              {data.pages.map((item) => (
                <button
                  key={item.id}
                  className={item.page_no === selectedPage ? 'active' : ''}
                  onClick={() => setActivePage(item.page_no)}
                >
                  <span>第 {item.page_no} 页</span>
                  <small>{item.text_source === 'ocr_paddle' ? 'OCR' : item.text_source}</small>
                </button>
              ))}
            </div>
          </aside>
          <section className="evidence-page glass">
            <div className="evidence-page-head">
              <div>
                <span className="eyebrow">原文证据</span>
                <h3>第 {selectedPage} 页</h3>
              </div>
              <div className="page-badges">
                <span>{page?.text_source === 'ocr_paddle' ? 'OCR 识别' : '内嵌文本'}</span>
                {page?.ocr_confidence != null && (
                  <span>置信度 {Math.round(page.ocr_confidence * 100)}%</span>
                )}
              </div>
            </div>
            <div className="document-blocks">
              {pageBlocks.length ? (
                pageBlocks.map((block) => (
                  <article className={`document-block ${block.block_type}`} key={block.id}>
                    <small>
                      {block.block_type} · 块 {block.sequence_no + 1}
                      {block.confidence != null
                        ? ` · ${Math.round(block.confidence * 100)}%`
                        : ''}
                    </small>
                    <p>{block.content_text}</p>
                    {block.bbox?.length === 4 && (
                      <code>坐标 [{block.bbox.map((value) => Math.round(value)).join(', ')}]</code>
                    )}
                  </article>
                ))
              ) : page?.text_content ? (
                <article className="document-block">
                  <p>{page.text_content}</p>
                </article>
              ) : (
                <EmptyInline text="本页没有可显示的正文" />
              )}
            </div>
            {pageTables.map((table) => {
              const rows = Array.from({ length: Math.min(table.row_count, 30) }, () =>
                Array.from({ length: Math.min(table.column_count, 12) }, () => ''),
              )
              table.cells.forEach((cell) => {
                if (rows[cell.row_index]?.[cell.column_index] !== undefined) {
                  rows[cell.row_index][cell.column_index] =
                    cell.normalized_text || cell.raw_text || ''
                }
              })
              return (
                <section className="parsed-table" key={table.id}>
                  <h4><Table2 size={16} /> {table.title || table.table_no}</h4>
                  <div className="table-scroll">
                    <table>
                      <tbody>
                        {rows.map((row, rowIndex) => (
                          <tr key={rowIndex}>
                            {row.map((cell, columnIndex) => (
                              <td key={columnIndex}>{cell || '—'}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              )
            })}
            {pageFigures.length > 0 && (
              <div className="figure-grid">
                {pageFigures.map((figure) => (
                  <figure key={figure.id}>
                    {figure.image_file_id ? (
                      <FigurePreview
                        projectId={projectId}
                        documentId={documentId}
                        figureId={figure.id}
                        alt={figure.caption || figure.figure_no}
                      />
                    ) : (
                      <div className="figure-placeholder">无图片文件</div>
                    )}
                    <figcaption>{figure.caption || figure.title || figure.figure_no}</figcaption>
                  </figure>
                ))}
              </div>
            )}
          </section>
        </div>
      ) : (
        <section className="panel glass">
          <EmptyInline text="文献尚未完成解析，点击“重新解析”创建任务" />
        </section>
      )}
    </div>
  )
}

function DocumentsSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<unknown>(null)
  const [selectedJob, setSelectedJob] = useState<JobItem | null>(null)
  const documents = useQuery({
    queryKey: ['documents', projectId],
    queryFn: () => api.documents(projectId),
  })
  const jobs = useQuery({
    queryKey: ['jobs', projectId],
    queryFn: () => api.jobs(projectId),
    refetchInterval: 5_000,
  })
  const upload = useMutation({
    mutationFn: (files: FileList) => api.uploadDocuments(projectId, files),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['documents', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['jobs', projectId] }),
      ])
    },
    onError: setError,
  })
  const runJob = useMutation({
    mutationFn: (jobId: string) => api.runJob(projectId, jobId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['jobs', projectId] }),
  })

  return (
    <div className="workspace-content">
      <SectionIntro
        eyebrow="文献智能解析"
        title="研究文献库"
        description="导入 PDF、DOCX、Excel、文本或安全压缩包，构建可追溯文献库。"
      />
      <label className="upload-zone glass">
        <input
          type="file"
          multiple
          accept=".pdf,.docx,.xlsx,.xls,.txt,.md,.zip"
          onChange={(event) => event.target.files?.length && upload.mutate(event.target.files)}
        />
        <span className="upload-icon">
          {upload.isPending ? <LoaderCircle className="spin" /> : <Upload />}
        </span>
        <strong>{upload.isPending ? '正在安全上传…' : '拖放或选择研究文献'}</strong>
        <small>PDF · DOCX · XLSX · TXT · MD · ZIP，单批文件将自动创建解析任务</small>
      </label>
      <ErrorNotice error={error || upload.error} />
      <div className="content-grid">
        <section className="panel glass span-two">
          <PanelHeading eyebrow="文献库" title={`${documents.data?.total || 0} 篇文献`} />
          {documents.isLoading ? (
            <LoadingPane />
          ) : documents.data?.items.length ? (
            <div className="record-list">
              {documents.data.items.map((document) => (
                <Link
                  className="record-row document-row"
                  key={document.id}
                  to={`/app/projects/${projectId}/documents/${document.id}`}
                >
                  <span className="record-icon">
                    <FileText size={17} />
                  </span>
                  <div>
                    <strong>{document.title || '未命名文献'}</strong>
                    <small>
                      {document.document_type} · {new Date(document.created_at).toLocaleDateString('zh-CN')}
                    </small>
                  </div>
                  <StatusPill value={document.parse_status || document.status} />
                  <ChevronRight size={16} />
                </Link>
              ))}
            </div>
          ) : (
            <EmptyInline text="文献库还是空的" />
          )}
        </section>
        <section className="panel glass">
          <PanelHeading eyebrow="处理进度" title="任务队列" />
          <div className="record-list compact">
            {jobs.data?.items.slice(0, 8).map((job) => (
              <JobRow
                key={job.id}
                job={job}
                action={
                  <div className="job-actions">
                    {job.status === 'queued' && (
                      <button className="mini-button" onClick={() => runJob.mutate(job.id)}>
                        立即执行
                      </button>
                    )}
                    <button className="mini-button" onClick={() => setSelectedJob(job)}>
                      查看日志
                    </button>
                  </div>
                }
              />
            ))}
          </div>
        </section>
      </div>
      <AnimatePresence>
        {selectedJob && (
          <TaskLogModal
            projectId={projectId}
            job={selectedJob}
            onClose={() => setSelectedJob(null)}
          />
        )}
      </AnimatePresence>
    </div>
  )
}

function SectionIntro({
  eyebrow,
  title,
  description,
  action,
}: {
  eyebrow: string
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="section-intro">
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {action}
    </div>
  )
}

function SearchSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [terms, setTerms] = useState('')
  const [name, setName] = useState('')
  const [mode, setMode] = useState<SearchMode>('hybrid')
  const [scope, setScope] = useState<SearchScope>('evidence_block')
  const [logic, setLogic] = useState<'AND' | 'OR'>('AND')
  const [fuzzyThreshold, setFuzzyThreshold] = useState(82)
  const [semanticThreshold, setSemanticThreshold] = useState(0.18)
  const [selectedRunId, setSelectedRunId] = useState('')
  const [reviewFilter, setReviewFilter] = useState<'all' | 'pending' | 'confirmed' | 'excluded'>('all')
  const searches = useQuery({
    queryKey: ['search-runs', projectId],
    queryFn: () => api.searchRuns(projectId),
    refetchInterval: 3_000,
  })
  const selectedRun = searches.data?.items.find((item) => item.id === selectedRunId)
  useEffect(() => {
    if (!selectedRunId && searches.data?.items[0]) {
      setSelectedRunId(searches.data.items[0].id)
    }
  }, [searches.data, selectedRunId])
  const results = useQuery({
    queryKey: ['search-results', projectId, selectedRunId],
    queryFn: () => api.searchResults(projectId, selectedRunId),
    enabled: Boolean(selectedRunId),
    refetchInterval: selectedRun && ['queued', 'running'].includes(selectedRun.status) ? 3_000 : false,
  })
  const create = useMutation({
    mutationFn: () =>
      api.createSearch(projectId, {
        terms: terms
          .split(/[,，\n]/)
          .map((item) => item.trim())
          .filter(Boolean),
        name: name || undefined,
        logic_operator: logic,
        match_scope: scope,
        search_mode: mode,
        fuzzy_threshold: fuzzyThreshold,
        semantic_threshold: semanticThreshold,
      }),
    onSuccess: (accepted) => {
      setTerms('')
      setName('')
      setSelectedRunId(accepted.resource_id)
      void Promise.all([
        queryClient.invalidateQueries({ queryKey: ['search-runs', projectId] }),
        queryClient.invalidateQueries({ queryKey: ['jobs', projectId] }),
      ])
    },
  })
  const review = useMutation({
    mutationFn: ({
      resultId,
      status,
    }: {
      resultId: string
      status: 'pending' | 'confirmed' | 'excluded'
    }) =>
      api.reviewSearchResult(projectId, selectedRunId, resultId, {
        review_status: status,
        is_included: status !== 'excluded',
      }),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: ['search-results', projectId, selectedRunId],
      }),
  })
  const modeLabels: Record<SearchMode, string> = {
    exact: '精确检索',
    fuzzy: '模糊检索',
    semantic: '语义检索',
    hybrid: '混合检索',
  }
  const scopeLabels: Record<SearchScope, string> = {
    evidence_block: '正文块',
    page: '页面',
    document: '整篇文献',
  }
  const visibleResults =
    results.data?.items.filter(
      (result) => reviewFilter === 'all' || result.review_status === reviewFilter,
    ) || []

  return (
    <div className="workspace-content">
      <SectionIntro
        eyebrow="混合检索"
        title="证据检索"
        description="融合精确、模糊与语义信号，定位跨文献研究证据。"
      />
      <div className="search-studio glass">
        <form
          onSubmit={(event) => {
            event.preventDefault()
            create.mutate()
          }}
        >
          <label>
            <span>检索名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="产率与温度证据" />
          </label>
          <label className="grow">
            <span>关键词，以逗号分隔</span>
            <input
              value={terms}
              onChange={(event) => setTerms(event.target.value)}
              placeholder="产率、温度、发酵时间"
              required
            />
          </label>
          <label>
            <span>检索方式</span>
            <select value={mode} onChange={(event) => setMode(event.target.value as SearchMode)}>
              {Object.entries(modeLabels).map(([value, label]) => (
                <option value={value} key={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>匹配范围</span>
            <select value={scope} onChange={(event) => setScope(event.target.value as SearchScope)}>
              {Object.entries(scopeLabels).map(([value, label]) => (
                <option value={value} key={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>关键词关系</span>
            <select value={logic} onChange={(event) => setLogic(event.target.value as 'AND' | 'OR')}>
              <option value="AND">全部满足（AND）</option>
              <option value="OR">任一满足（OR）</option>
            </select>
          </label>
          {(mode === 'fuzzy' || mode === 'hybrid') && (
            <label>
              <span>模糊阈值：{fuzzyThreshold}</span>
              <input
                type="range"
                min="50"
                max="100"
                value={fuzzyThreshold}
                onChange={(event) => setFuzzyThreshold(Number(event.target.value))}
              />
            </label>
          )}
          {(mode === 'semantic' || mode === 'hybrid') && (
            <label>
              <span>语义阈值：{semanticThreshold.toFixed(2)}</span>
              <input
                type="range"
                min="0"
                max="1"
                step="0.01"
                value={semanticThreshold}
                onChange={(event) => setSemanticThreshold(Number(event.target.value))}
              />
            </label>
          )}
          <button className="button button-primary" disabled={create.isPending}>
            {create.isPending ? <LoaderCircle className="spin" size={16} /> : <Search size={16} />}
            开始检索
          </button>
        </form>
        <ErrorNotice error={create.error} />
      </div>
      <div className="search-workbench">
        <aside className="search-history glass">
          <PanelHeading eyebrow="检索历史" title={`${searches.data?.total || 0} 次运行`} />
          {searches.isLoading ? (
            <LoadingPane />
          ) : searches.data?.items.length ? (
            <div className="search-run-list">
              {searches.data.items.map((run: SearchRun) => (
                <button
                  key={run.id}
                  className={run.id === selectedRunId ? 'active' : ''}
                  onClick={() => setSelectedRunId(run.id)}
                >
                  <span>
                    <strong>{run.name || run.terms.join('、') || '未命名检索'}</strong>
                    <small>{modeLabels[run.search_mode]} · {run.terms.join('、')}</small>
                  </span>
                  <span>
                    <StatusPill value={run.status} />
                    <b>{run.result_count}</b>
                  </span>
                </button>
              ))}
            </div>
          ) : (
            <EmptyInline text="尚未执行检索" />
          )}
        </aside>
        <section className="search-results glass">
          <div className="search-results-head">
            <div>
              <span className="eyebrow">检索证据</span>
              <h3>{selectedRun?.name || '选择一次检索运行'}</h3>
              {selectedRun && (
                <p>
                  {modeLabels[selectedRun.search_mode]} · {scopeLabels[selectedRun.match_scope]} ·
                  {selectedRun.logic_operator === 'AND' ? ' 全部关键词' : ' 任一关键词'}
                </p>
              )}
            </div>
            <div className="review-filters">
              {(['all', 'pending', 'confirmed', 'excluded'] as const).map((filter) => (
                <button
                  key={filter}
                  className={reviewFilter === filter ? 'active' : ''}
                  onClick={() => setReviewFilter(filter)}
                >
                  {{ all: '全部', pending: '待审核', confirmed: '已确认', excluded: '已排除' }[filter]}
                </button>
              ))}
            </div>
          </div>
          <ErrorNotice error={results.error || review.error} />
          {results.isLoading ? (
            <LoadingPane label="正在读取检索结果" />
          ) : selectedRun && ['queued', 'running'].includes(selectedRun.status) ? (
            <div className="search-running">
              <LoaderCircle className="spin" />
              <strong>正在检索文献证据</strong>
              <p>结果会在后台任务完成后自动显示。</p>
            </div>
          ) : visibleResults.length ? (
            <div className="evidence-result-list">
              {visibleResults.map((result) => (
                <article className={`evidence-result ${result.review_status}`} key={result.id}>
                  <header>
                    <div>
                      <span>结果 #{result.result_no}</span>
                      <strong>{result.document_title || '未命名文献'} · 第 {result.page_no} 页</strong>
                    </div>
                    <span className="evidence-score">{Math.round(Number(result.score || 0))}%</span>
                  </header>
                  {result.previous_context && <p className="context-fade">{result.previous_context}</p>}
                  <blockquote>{result.matched_context}</blockquote>
                  {result.next_context && <p className="context-fade">{result.next_context}</p>}
                  <div className="matched-term-list">
                    {result.matched_terms.map((term, index) => (
                      <span className={term.matched ? 'matched' : ''} key={`${term.term}-${index}`}>
                        {term.term} · {Math.round(term.score)}%
                      </span>
                    ))}
                  </div>
                  <footer>
                    <Link
                      className="mini-button"
                      to={`/app/projects/${projectId}/documents/${result.document_id}?page=${result.page_no}`}
                    >
                      查看原文证据 <ChevronRight size={13} />
                    </Link>
                    <div>
                      {result.review_status !== 'confirmed' && (
                        <button
                          className="mini-button confirm"
                          disabled={review.isPending}
                          onClick={() => review.mutate({ resultId: result.id, status: 'confirmed' })}
                        >
                          <CircleCheck size={13} /> 确认
                        </button>
                      )}
                      {result.review_status !== 'excluded' && (
                        <button
                          className="mini-button exclude"
                          disabled={review.isPending}
                          onClick={() => review.mutate({ resultId: result.id, status: 'excluded' })}
                        >
                          <X size={13} /> 排除
                        </button>
                      )}
                      {result.review_status !== 'pending' && (
                        <button
                          className="mini-button"
                          disabled={review.isPending}
                          onClick={() => review.mutate({ resultId: result.id, status: 'pending' })}
                        >
                          <RotateCcw size={13} /> 恢复
                        </button>
                      )}
                    </div>
                  </footer>
                </article>
              ))}
            </div>
          ) : (
            <EmptyInline text={selectedRunId ? '当前筛选下没有检索结果' : '请先创建或选择检索运行'} />
          )}
        </section>
      </div>
    </div>
  )
}

function RecordsSection({
  title,
  eyebrow,
  description,
  queryKey,
  queryFn,
  unwrap,
}: {
  title: string
  eyebrow: string
  description: string
  queryKey: string[]
  queryFn: () => Promise<unknown>
  unwrap?: (data: unknown) => GenericRecord[]
}) {
  const query = useQuery({ queryKey, queryFn })
  const records = query.data ? (unwrap ? unwrap(query.data) : (query.data as GenericRecord[])) : []
  return (
    <div className="workspace-content">
      <SectionIntro eyebrow={eyebrow} title={title} description={description} />
      <ErrorNotice error={query.error} />
      <RecordsPanel records={records} loading={query.isLoading} empty="当前还没有记录" />
    </div>
  )
}

function RecordsPanel({
  records,
  loading,
  empty,
}: {
  records: GenericRecord[]
  loading: boolean
  empty: string
}) {
  return (
    <section className="panel glass">
      <PanelHeading eyebrow="当前记录" title={`共 ${records.length} 条`} />
      {loading ? (
        <LoadingPane />
      ) : records.length ? (
        <div className="record-list">
          {records.map((record) => (
            <div className="record-row generic-row" key={record.id}>
              <span className="record-icon">
                <Gem size={16} />
              </span>
              <div>
                <strong>{String(record.name || record.title || record.canonical_name || record.id)}</strong>
                <small>
                  {String(
                    record.description ||
                      record.created_at ||
                      record.updated_at ||
                      '可信研究记录',
                  )}
                </small>
              </div>
              <StatusPill value={record.status || record.review_status || 'active'} />
            </div>
          ))}
        </div>
      ) : (
        <EmptyInline text={empty} />
      )}
    </section>
  )
}

function ExtractionSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [schemaId, setSchemaId] = useState('')
  const schemas = useQuery({
    queryKey: ['field-schemas', projectId],
    queryFn: () => api.fieldSchemas(projectId),
  })
  const extractions = useQuery({
    queryKey: ['extractions', projectId],
    queryFn: () => api.extractions(projectId),
  })
  const create = useMutation({
    mutationFn: () => api.createExtraction(projectId, schemaId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['extractions', projectId] }),
  })
  return (
    <div className="workspace-content">
      <SectionIntro
        eyebrow="结构化证据"
        title="数据抽取工作台"
        description="按照冻结字段方案，将文献证据转化为结构化记录。"
      />
      <form
        className="inline-creator glass"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate()
        }}
      >
        <select value={schemaId} onChange={(event) => setSchemaId(event.target.value)} required>
          <option value="">选择字段方案</option>
          {schemas.data?.map((schema) => (
            <option key={schema.id} value={schema.id}>
              {String(schema.name)}
            </option>
          ))}
        </select>
        <button className="button button-primary" disabled={create.isPending}>
          <Sparkles size={16} /> 创建抽取任务
        </button>
      </form>
      <ErrorNotice error={create.error} />
      <RecordsPanel records={extractions.data || []} loading={extractions.isLoading} empty="暂无抽取运行" />
    </div>
  )
}

function DatasetsSection({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient()
  const [name, setName] = useState('')
  const [runId, setRunId] = useState('')
  const datasets = useQuery({
    queryKey: ['datasets', projectId],
    queryFn: () => api.datasets(projectId),
  })
  const extractions = useQuery({
    queryKey: ['extractions', projectId],
    queryFn: () => api.extractions(projectId),
  })
  const create = useMutation({
    mutationFn: () => api.createDataset(projectId, name, runId),
    onSuccess: () => {
      setName('')
      setRunId('')
      queryClient.invalidateQueries({ queryKey: ['datasets', projectId] })
    },
  })
  return (
    <div className="workspace-content">
      <SectionIntro
        eyebrow="可信数据资产"
        title="数据集仓库"
        description="构建、审核并冻结可复现的数据集版本。"
      />
      <form
        className="inline-creator glass"
        onSubmit={(event) => {
          event.preventDefault()
          create.mutate()
        }}
      >
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="数据集名称" required />
        <select value={runId} onChange={(event) => setRunId(event.target.value)} required>
          <option value="">选择抽取运行</option>
          {extractions.data?.map((run) => (
            <option value={run.id} key={run.id}>
              {String(run.name || run.id)}
            </option>
          ))}
        </select>
        <button className="button button-primary" disabled={create.isPending}>
          <Plus size={16} /> 构建数据集
        </button>
      </form>
      <ErrorNotice error={create.error} />
      <RecordsPanel records={datasets.data || []} loading={datasets.isLoading} empty="暂无数据资产" />
    </div>
  )
}

function ReportsSection({ projectId }: { projectId: string }) {
  const reports = useQuery({
    queryKey: ['reports', projectId],
    queryFn: () => api.reports(projectId),
  })
  return (
    <div className="workspace-content">
      <SectionIntro
        eyebrow="研究成果输出"
        title="研究报告"
        description="将数据、模型结果与证据索引汇聚为专业研究报告。"
      />
      <section className="panel glass">
        <PanelHeading eyebrow="已生成报告" title={`共 ${reports.data?.length || 0} 份`} />
        {reports.isLoading ? (
          <LoadingPane />
        ) : reports.data?.length ? (
          <div className="record-list">
            {reports.data.map((report) => (
              <div className="record-row" key={report.id}>
                <span className="record-icon">
                  <FileText size={16} />
                </span>
                <div>
                  <strong>{String(report.title || '研究报告')}</strong>
                  <small>{String(report.created_at || '')}</small>
                </div>
                <StatusPill value={report.status} />
                <button
                  className="mini-button"
                  onClick={() =>
                    api.downloadReport(projectId, report.id, String(report.title || '研究报告'))
                  }
                >
                  <Download size={14} /> 下载
                </button>
              </div>
            ))}
          </div>
        ) : (
          <EmptyInline text="暂无生成报告" />
        )}
      </section>
    </div>
  )
}

function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/auth" element={<AuthPage />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <DashboardPage />
            </RequireAuth>
          }
        />
        <Route
          path="/app/projects/:projectId/documents/:documentId"
          element={
            <RequireAuth>
              <WorkspacePage />
            </RequireAuth>
          }
        />
        <Route
          path="/app/projects/:projectId/:section?"
          element={
            <RequireAuth>
              <WorkspacePage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
  )
}

export default App
