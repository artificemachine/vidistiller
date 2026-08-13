import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet },
}));

vi.mock('@/lib/authStore', () => ({
  useAuthStore: () => ({ isAuthenticated: true }),
}));

import LlmNavStatus from '@/components/LlmNavStatus';

const healthy = {
  provider: 'vllm',
  model: 'qwen3.6-27b-awq',
  base_url: 'http://192.0.2.1:8000',
  reachable: true,
  auth_ok: null,
  model_found: true,
  models_available: ['qwen3.6-27b-awq'],
  latency_ms: 42,
  error: null,
  fleet_node: 'secondary',
};

describe('LlmNavStatus', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('shows green dot with provider and model when healthy', async () => {
    mockGet.mockResolvedValue({ data: healthy });
    render(<LlmNavStatus />);

    await waitFor(() => {
      expect(screen.getByText('vllm · qwen3.6-27b-awq')).toBeInTheDocument();
    });
    expect(screen.getByTestId('llm-nav-dot').className).toContain('bg-green-500');
  });

  it('shows red dot when unreachable', async () => {
    mockGet.mockResolvedValue({
      data: { ...healthy, reachable: false, model_found: false, error: 'connection refused' },
    });
    render(<LlmNavStatus />);

    await waitFor(() => {
      expect(screen.getByText('vllm · qwen3.6-27b-awq')).toBeInTheDocument();
    });
    expect(screen.getByTestId('llm-nav-dot').className).toContain('bg-red-500');
    expect(screen.getByTitle(/not reachable/)).toBeInTheDocument();
  });

  it('shows amber dot when model not available', async () => {
    mockGet.mockResolvedValue({
      data: { ...healthy, model_found: false, models_available: ['other-model'] },
    });
    render(<LlmNavStatus />);

    await waitFor(() => {
      expect(screen.getByText('vllm · qwen3.6-27b-awq')).toBeInTheDocument();
    });
    expect(screen.getByTestId('llm-nav-dot').className).toContain('bg-amber-500');
  });

  it('refetches when clicked', async () => {
    const user = userEvent.setup();
    mockGet.mockResolvedValue({ data: healthy });
    render(<LlmNavStatus />);

    await waitFor(() => {
      expect(screen.getByText('vllm · qwen3.6-27b-awq')).toBeInTheDocument();
    });
    expect(mockGet).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole('button', { name: /llm/i }));
    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });

  it('hides on endpoint failure (e.g. unauthenticated)', async () => {
    mockGet.mockRejectedValue(new Error('401'));
    render(<LlmNavStatus />);

    await waitFor(() => {
      expect(screen.queryByText(/vllm|ollama/)).not.toBeInTheDocument();
    });
  });
});
