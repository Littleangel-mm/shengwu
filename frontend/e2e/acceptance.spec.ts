import { expect, test, type Page } from '@playwright/test'

const PASSWORD = 'E2ePass!2026#Aa'

function randomEmail() {
  return `e2e-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`
}

async function registerNewAccount(page: Page) {
  const email = randomEmail()
  await page.goto('/auth?mode=register')
  await expect(page.getByRole('heading', { name: '创建专属研究空间' })).toBeVisible()
  await page.getByLabel('姓名').fill('端到端验收员')
  await page.getByLabel('邮箱').fill(email)
  await page.getByLabel('密码').fill(PASSWORD)
  await page.getByRole('button', { name: '创建账户' }).click()
  await expect(page).toHaveURL(/\/app$/)
  await expect(page.getByRole('heading', { name: '研究项目总览' })).toBeVisible()
  return email
}

async function createOrganizationAndProject(page: Page) {
  const suffix = Date.now().toString(36)
  const orgName = `验收组织-${suffix}`
  const projectName = `验收项目-${suffix}`

  await page.getByRole('button', { name: '新建组织' }).click()
  await expect(page.getByRole('heading', { name: '创建研究组织' })).toBeVisible()
  await page.getByLabel('组织名称').fill(orgName)
  await page.getByRole('button', { name: '确认创建' }).click()
  await expect(page.getByRole('heading', { name: '创建研究组织' })).toBeHidden()

  await page.getByRole('button', { name: '新建项目' }).click()
  await expect(page.getByRole('heading', { name: '创建研究项目' })).toBeVisible()
  await page.getByLabel('所属组织').selectOption({ label: orgName })
  await page.getByLabel('项目名称').fill(projectName)
  await page.getByLabel('研究领域').fill('生物发酵')
  await page.getByRole('button', { name: '确认创建' }).click()
  await expect(page.getByRole('heading', { name: '创建研究项目' })).toBeHidden()

  return { orgName, projectName }
}

async function openWorkspace(page: Page, projectName: string) {
  await page.getByRole('link', { name: new RegExp(projectName) }).click()
  await expect(page).toHaveURL(/\/app\/projects\/[0-9a-f-]+\/overview$/)
  await expect(page.locator('.project-identity')).toContainText(projectName)
}

test('落地页渲染并可进入登录页', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('.hero-copy h1')).toContainText('从科研文献')
  await expect(page.getByRole('heading', { name: '复杂科研流程，凝练为一套优雅系统。' })).toBeVisible()

  await page.locator('.landing-nav').getByRole('link', { name: '登录' }).click()
  await expect(page).toHaveURL(/\/auth$/)
  await expect(page.getByRole('heading', { name: '回到研究现场' })).toBeVisible()
  await expect(page.getByRole('button', { name: '安全登录' })).toBeVisible()
})

test('注册新账号并创建组织、项目后进入工作台', async ({ page }) => {
  await registerNewAccount(page)
  const { projectName } = await createOrganizationAndProject(page)
  await openWorkspace(page, projectName)
  await expect(page.getByRole('heading', { name: '项目概览' })).toBeVisible()
})

test('工作台侧边导航切换并渲染各分区标题', async ({ page }) => {
  await registerNewAccount(page)
  const { projectName } = await createOrganizationAndProject(page)
  await openWorkspace(page, projectName)

  const sections: Array<[navLabel: string, sectionKey: string, sectionTitle: string]> = [
    ['文献管理', 'documents', '研究文献库'],
    ['证据检索', 'search', '证据检索'],
    ['术语与字段', 'terms', '术语与字段方案'],
    ['数据集', 'datasets', '数据集仓库'],
    ['模型实验', 'models', '智能建模实验室'],
    ['研究报告', 'reports', '研究报告'],
    ['成员权限', 'members', '成员管理'],
  ]

  for (const [navLabel, sectionKey, sectionTitle] of sections) {
    await page
      .locator('.workspace-nav')
      .getByRole('link', { name: navLabel, exact: true })
      .click()
    await expect(page).toHaveURL(new RegExp(`/app/projects/[0-9a-f-]+/${sectionKey}$`))
    await expect(page.locator('.section-intro h2')).toHaveText(sectionTitle)
  }
})
