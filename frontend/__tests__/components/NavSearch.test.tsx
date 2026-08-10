import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet },
}));

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('@/lib/authStore', () => ({
  useAuthStore: () => ({ isAuthenticated: true }),
}));

import NavSearch from '@/components/NavSearch';

const results = [
  {
    job_id: 'job-1',
    status: 'completed',
    video_title: 'Kubernetes Ingress Tutorial',
    video_url: 'https://www.youtube.com/watch?v=abc',
    created_at: '2026-08-01T00:00:00Z',
  },
];

describe('NavSearch', () => {
  beforeEach(() => {
    mockGet.mockReset();
    mockPush.mockReset();
  });

  it('does not query until the user types', () => {
    render(<NavSearch />);
    expect(mockGet).not.toHaveBeenCalled();
  });

  it('debounces and queries GET /jobs?q=... with the typed text', async () => {
    mockGet.mockResolvedValue({ data: results });
    const user = userEvent.setup();
    render(<NavSearch />);

    await user.type(screen.getByPlaceholderText(/search conversions/i), 'kubernetes');

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledWith('/jobs', { params: { q: 'kubernetes', limit: 20 } });
    });
  });

  it('shows matching results in a dropdown', async () => {
    mockGet.mockResolvedValue({ data: results });
    const user = userEvent.setup();
    render(<NavSearch />);

    await user.type(screen.getByPlaceholderText(/search conversions/i), 'kubernetes');

    expect(await screen.findByText('Kubernetes Ingress Tutorial')).toBeInTheDocument();
  });

  it('shows "no matches" when the search returns empty', async () => {
    mockGet.mockResolvedValue({ data: [] });
    const user = userEvent.setup();
    render(<NavSearch />);

    await user.type(screen.getByPlaceholderText(/search conversions/i), 'zzz');

    expect(await screen.findByText(/no matches/i)).toBeInTheDocument();
  });

  it('navigates to the job on result click', async () => {
    mockGet.mockResolvedValue({ data: results });
    const user = userEvent.setup();
    render(<NavSearch />);

    await user.type(screen.getByPlaceholderText(/search conversions/i), 'kubernetes');
    const result = await screen.findByText('Kubernetes Ingress Tutorial');
    await user.click(result);

    expect(mockPush).toHaveBeenCalledWith('/jobs/job-1');
  });
});
