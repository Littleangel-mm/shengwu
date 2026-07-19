import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, expect, it } from 'vitest'
import App, { StatusPill } from './App'

describe('status presentation', () => {
  it('localizes running state', () => {
    render(<StatusPill value="running" />)
    expect(screen.getByText('运行中')).toBeInTheDocument()
  })
})

describe('landing workflow', () => {
  it('offers authentication and product entry points', () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <MemoryRouter initialEntries={['/']}>
        <QueryClientProvider client={client}>
          <App />
        </QueryClientProvider>
      </MemoryRouter>,
    )
    expect(screen.getByRole('heading', { name: /从科研文献到智能洞察/ })).toBeInTheDocument()
    expect(screen.getAllByRole('link', { name: /开启研究空间|进入研究空间/ }).length).toBeGreaterThan(0)
  })
})
