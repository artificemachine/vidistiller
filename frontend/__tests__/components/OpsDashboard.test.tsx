import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';

const { mockSwr, mockAuth } = vi.hoisted(() => ({
  mockSwr: vi.fn(),
  mockAuth: vi.fn(),
}));

vi.mock('swr', () => ({
  default: (...args: unknown[]) => mockSwr(...args),
}));

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn() },
}));

vi.mock('@/lib/authStore', () => ({
  useAuthStore: () => mockAuth(),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

import OpsDashboard from '@/components/OpsDashboard';

const JOBS = [
  {
    job_id: 'job-1',
    owner_id: 1,
    owner_username: 'alice',
    status: 'processing',
    error_message: null,
    admission_state: 'admitted',
    queue_reason: null,
    queue_position: null,
    sidecar_id: 'sidecar-a',
    model: 'sidecar-a',
    elapsed_seconds: 125,
    progress: 42,
    processing_mode: 'standard',
    created_at: '2026-02-08T09:00:00Z',
  },
  {
    job_id: 'job-2',
    owner_id: 2,
    owner_username: 'bob',
    status: 'pending',
    error_message: null,
    admission_state: 'queued',
    queue_reason: 'no capacity',
    queue_position: 3,
    sidecar_id: null,
    model: null,
    elapsed_seconds: 0,
    progress: null,
    processing_mode: null,
    created_at: '2026-02-08T09:05:00Z',
  },
];

const SIDECARS = [
  {
    registered_id: 'sidecar-a',
    label: 'Primary',
    healthy: true,
    served_models: ['gemma4-31b'],
    declared_model: null,
    running_requests: 2,
    waiting_requests: 1,
    reserved_slots: 3,
    total_slots: 4,
    vram_used_mib: 100,
    vram_total_mib: 200,
    stale: false,
  },
];

function mockEndpoints(jobsResult: unknown, sidecarsResult: unknown) {
  mockSwr.mockImplementation((key: string) => {
    if (key === '/ops/jobs') return jobsResult;
    if (key === '/ops/sidecars') return sidecarsResult;
    return {};
  });
}

describe('OpsDashboard', () => {
  beforeEach(() => {
    mockSwr.mockReset();
    mockAuth.mockReset();
    mockAuth.mockReturnValue({ isAuthenticated: true, isLoading: false });
  });

  it('renders job rows with owner, status, admission, sidecar, elapsed, progress, created', () => {
    mockEndpoints({ data: JOBS, error: undefined }, { data: SIDECARS, error: undefined });
    render(<OpsDashboard />);

    expect(screen.getByText('alice')).toBeInTheDocument();
    expect(screen.getByText('bob')).toBeInTheDocument();
    expect(screen.getByText('processing')).toBeInTheDocument();
    expect(screen.getByText('pending')).toBeInTheDocument();

    // Admission badge + queue reason/position for the queued job
    expect(screen.getByText('admitted')).toBeInTheDocument();
    expect(screen.getByText('queued')).toBeInTheDocument();
    expect(screen.getByText('no capacity')).toBeInTheDocument();
    expect(screen.getByTestId('queue-position')).toHaveTextContent('position #3');

    // Sidecar / model
    expect(screen.getByText('(sidecar-a)')).toBeInTheDocument();

    // Elapsed + progress
    expect(screen.getByText('2m 5s')).toBeInTheDocument();
    expect(screen.getByText('42%')).toBeInTheDocument();
  });

  it('renders the sidecar status strip with health, served model and slots', () => {
    mockEndpoints({ data: JOBS, error: undefined }, { data: SIDECARS, error: undefined });
    render(<OpsDashboard />);

    expect(screen.getByText('Primary')).toBeInTheDocument();
    expect(screen.getByText(/gemma4-31b/)).toBeInTheDocument();
    expect(screen.getByText('slots: 3/4 reserved')).toBeInTheDocument();
    expect(screen.getAllByTestId('sidecar-card')).toHaveLength(1);
    expect(screen.getByTestId('sidecar-health').className).toContain('bg-success');
  });

  it('shows an empty state when there are no jobs', () => {
    mockEndpoints({ data: [], error: undefined }, { data: SIDECARS, error: undefined });
    render(<OpsDashboard />);
    expect(screen.getByText('no jobs yet.')).toBeInTheDocument();
  });

  it('shows the login notice when the user is not authenticated', () => {
    mockAuth.mockReturnValue({ isAuthenticated: false, isLoading: false });
    mockEndpoints({ data: undefined, error: undefined }, { data: undefined, error: undefined });
    render(<OpsDashboard />);
    expect(screen.getByText(/log in with an operator account/i)).toBeInTheDocument();
  });

  it('shows an operator-access notice when the ops endpoints return 403/404', () => {
    const denied = { data: undefined, error: { response: { status: 404 } } };
    mockEndpoints(denied, denied);
    render(<OpsDashboard />);
    expect(screen.getByTestId('ops-access-denied')).toBeInTheDocument();
    expect(screen.getByText(/operator access required/i)).toBeInTheDocument();
  });
});
