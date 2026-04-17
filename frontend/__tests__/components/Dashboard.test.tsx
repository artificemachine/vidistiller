import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet, mockPost, mockDelete, mockReplace } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockDelete: vi.fn(),
  mockReplace: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet, post: mockPost, delete: mockDelete },
  apiClient: { get: mockGet, post: mockPost, delete: mockDelete },
}));

// Mock next/link
vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

// Mock next/navigation
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mockReplace, push: vi.fn(), back: vi.fn() }),
}));

// Mock auth store — default to authenticated
vi.mock('@/lib/authStore', () => ({
  useAuthStore: () => ({ isAuthenticated: true, isLoading: false }),
}));

import Dashboard from '@/app/dashboard/page';

const MOCK_JOBS = [
  { job_id: 'aaaa1111-0000-0000-0000-000000000001', status: 'completed', created_at: '2026-02-05T10:00:00Z', updated_at: '2026-02-05T11:00:00Z' },
  { job_id: 'bbbb2222-0000-0000-0000-000000000002', status: 'processing', created_at: '2026-02-08T09:00:00Z', updated_at: '2026-02-08T09:30:00Z' },
  { job_id: 'cccc3333-0000-0000-0000-000000000003', status: 'failed', created_at: '2026-01-15T14:00:00Z', updated_at: '2026-01-15T15:00:00Z' },
  { job_id: 'dddd4444-0000-0000-0000-000000000004', status: 'pending', created_at: '2026-02-07T08:00:00Z', updated_at: '2026-02-07T08:00:00Z' },
];

function renderDashboard() {
  return render(<Dashboard />);
}

describe('Dashboard', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockGet.mockResolvedValue({ data: MOCK_JOBS });
  });

  it('renders loading state initially', () => {
    mockGet.mockReturnValue(new Promise(() => {})); // never resolves
    renderDashboard();
    expect(screen.getByText('loading jobs...')).toBeInTheDocument();
  });

  it('renders jobs table after fetch', async () => {
    renderDashboard();
    expect(await screen.findByText('jobs dashboard')).toBeInTheDocument();
    expect(screen.getByText('completed')).toBeInTheDocument();
    expect(screen.getByText('processing')).toBeInTheDocument();
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('renders toolbar controls when jobs exist', async () => {
    renderDashboard();
    await screen.findByText('jobs dashboard');
    expect(screen.getByText('all months')).toBeInTheDocument();
    expect(screen.getByText('newest first')).toBeInTheDocument();
    expect(screen.getByText('stop all')).toBeInTheDocument();
    expect(screen.getByText('clear history')).toBeInTheDocument();
  });

  it('renders empty state without toolbar', async () => {
    mockGet.mockResolvedValue({ data: [] });
    renderDashboard();
    expect(await screen.findByText('get started with vidistiller')).toBeInTheDocument();
    expect(screen.getByText('convert your first video')).toBeInTheDocument();
    expect(screen.queryByText('stop all')).not.toBeInTheDocument();
    expect(screen.queryByText('clear history')).not.toBeInTheDocument();
  });

  it('renders month filter options from job dates', async () => {
    renderDashboard();
    await screen.findByText('jobs dashboard');
    const select = screen.getByDisplayValue('all months');
    const options = within(select).getAllByRole('option');
    // "all months" + 2 distinct months (Feb 2026, Jan 2026)
    expect(options.length).toBe(3);
    expect(options[1]).toHaveTextContent('Feb 2026');
    expect(options[2]).toHaveTextContent('Jan 2026');
  });

  it('filters jobs by month', async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText('jobs dashboard');
    const monthSelect = screen.getByDisplayValue('all months');
    await user.selectOptions(monthSelect, '2026-01');
    // Only the January job (failed) should remain visible
    expect(screen.getByText('failed')).toBeInTheDocument();
    expect(screen.queryByText('completed')).not.toBeInTheDocument();
    expect(screen.queryByText('processing')).not.toBeInTheDocument();
  });

  it('sorts by status when dropdown changed', async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText('jobs dashboard');
    const sortSelect = screen.getByDisplayValue('newest first');
    await user.selectOptions(sortSelect, 'status_asc');
    const rows = screen.getAllByRole('row');
    // header + 4 data rows; first data row should be pending (lowest status order)
    const firstDataRow = rows[1];
    expect(within(firstDataRow).getByText('pending')).toBeInTheDocument();
  });

  it('toggles sort when clicking Status header', async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText('jobs dashboard');
    const statusBtn = screen.getByRole('button', { name: /status/i });
    await user.click(statusBtn);
    // Should switch to status_asc
    const rows = screen.getAllByRole('row');
    expect(within(rows[1]).getByText('pending')).toBeInTheDocument();
    // Click again to toggle to status_desc
    await user.click(statusBtn);
    const rows2 = screen.getAllByRole('row');
    expect(within(rows2[1]).getByText('failed')).toBeInTheDocument();
  });

  it('toggles sort when clicking Created header', async () => {
    const user = userEvent.setup();
    renderDashboard();
    await screen.findByText('jobs dashboard');
    const createdBtn = screen.getByRole('button', { name: /created/i });
    // Default is newest, click switches to oldest
    await user.click(createdBtn);
    const rows = screen.getAllByRole('row');
    // Oldest job is Jan 2026 (failed)
    expect(within(rows[1]).getByText('failed')).toBeInTheDocument();
  });

  it('shows error state with retry button (no empty state overlap)', async () => {
    mockGet.mockRejectedValue(new Error('Network error'));
    renderDashboard();
    expect(await screen.findByText('Failed to load jobs')).toBeInTheDocument();
    expect(screen.getByText('retry')).toBeInTheDocument();
    // Empty state should NOT appear alongside the error
    expect(screen.queryByText('get started with vidistiller')).not.toBeInTheDocument();
  });
});
