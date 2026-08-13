import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet },
}));

import LlmStatusCard from '@/components/LlmStatusCard';

const healthy = {
  provider: 'vllm',
  model: 'gemma4-31b',
  base_url: 'http://primary:8000',
  reachable: true,
  auth_ok: null,
  model_found: true,
  models_available: ['gemma4-31b'],
  latency_ms: 42,
  error: null,
  fleet_node: 'primary',
};

describe('LlmStatusCard', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('shows checking state while loading', () => {
    mockGet.mockReturnValue(new Promise(() => {})); // never resolves
    render(<LlmStatusCard />);
    expect(screen.getByText('checking...')).toBeInTheDocument();
  });

  it('shows green ready state when model is reachable', async () => {
    mockGet.mockResolvedValue({ data: healthy });
    render(<LlmStatusCard />);

    await waitFor(() => {
      expect(screen.getByText('vllm · gemma4-31b')).toBeInTheDocument();
    });
    expect(screen.getByText('— ready')).toBeInTheDocument();
    expect(screen.getByTestId('llm-status-dot').className).toContain('bg-green-500');
    expect(screen.getByText('42ms')).toBeInTheDocument();
    expect(screen.getByText('fleet node: primary')).toBeInTheDocument();
    expect(screen.getByTestId('llm-status-url')).toHaveTextContent('http://primary:8000');
  });

  it('shows red state when endpoint is unreachable', async () => {
    mockGet.mockResolvedValue({
      data: { ...healthy, reachable: false, model_found: false, latency_ms: 0, error: 'connection refused' },
    });
    render(<LlmStatusCard />);

    await waitFor(() => {
      expect(screen.getByText('— not reachable')).toBeInTheDocument();
    });
    expect(screen.getByTestId('llm-status-dot').className).toContain('bg-red-500');
    expect(screen.getByText('connection refused')).toBeInTheDocument();
  });

  it('shows amber state when reachable but model is not loaded', async () => {
    mockGet.mockResolvedValue({
      data: { ...healthy, model_found: false, models_available: ['other-model'] },
    });
    render(<LlmStatusCard />);

    await waitFor(() => {
      expect(screen.getByText('— reachable, model not available')).toBeInTheDocument();
    });
    expect(screen.getByTestId('llm-status-dot').className).toContain('bg-amber-500');
    expect(screen.getByTestId('llm-status-available')).toHaveTextContent('available: other-model');
  });

  it('shows red state when the api key is rejected', async () => {
    mockGet.mockResolvedValue({
      data: { ...healthy, provider: 'openai', auth_ok: false, error: 'api key rejected (HTTP 401)' },
    });
    render(<LlmStatusCard />);

    await waitFor(() => {
      expect(screen.getByText('— api key rejected')).toBeInTheDocument();
    });
    expect(screen.getByTestId('llm-status-dot').className).toContain('bg-red-500');
  });

  it('handles the diagnostics endpoint itself failing', async () => {
    mockGet.mockRejectedValue(new Error('network'));
    render(<LlmStatusCard />);

    await waitFor(() => {
      expect(screen.getByText('status unavailable')).toBeInTheDocument();
    });
    expect(screen.getByText('could not fetch llm status from the server.')).toBeInTheDocument();
  });

  it('refetches when the refresh button is clicked', async () => {
    const user = userEvent.setup();
    mockGet.mockResolvedValue({ data: healthy });
    render(<LlmStatusCard />);

    await waitFor(() => {
      expect(screen.getByText('vllm · gemma4-31b')).toBeInTheDocument();
    });
    expect(mockGet).toHaveBeenCalledTimes(1);

    await user.click(screen.getByText('refresh'));

    await waitFor(() => {
      expect(mockGet).toHaveBeenCalledTimes(2);
    });
    expect(mockGet).toHaveBeenLastCalledWith('/diagnostics/llm');
  });

  it('refetches when refreshToken changes', async () => {
    mockGet.mockResolvedValue({ data: healthy });
    const { rerender } = render(<LlmStatusCard refreshToken={0} />);

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(1));

    rerender(<LlmStatusCard refreshToken={1} />);

    await waitFor(() => expect(mockGet).toHaveBeenCalledTimes(2));
  });
});
