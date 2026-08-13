import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet } = vi.hoisted(() => ({ mockGet: vi.fn() }));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet, patch: vi.fn(), delete: vi.fn() },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: vi.fn(), push: vi.fn() }),
}));

vi.mock('@/lib/authStore', () => ({
  useAuthStore: () => ({
    user: {
      llm_provider: 'vllm',
      llm_model: 'qwen3.6-27b-awq',
      llm_ollama_url: 'http://192.0.2.10:8000',
      has_api_key: false,
    },
    isAuthenticated: true,
    isLoading: false,
  }),
}));

// Stub the status card (it does its own /diagnostics/llm fetch)
vi.mock('@/components/LlmStatusCard', () => ({
  default: () => <div data-testid="llm-status-card" />,
}));

import SettingsPage from '@/app/settings/page';

describe('SettingsPage — vllm models probe must not block the form', () => {
  beforeEach(() => {
    mockGet.mockReset();
  });

  it('renders the form even when the vllm models probe never resolves', async () => {
    // /settings/me and /settings/vllm/fleet resolve immediately
    mockGet.mockImplementation((url: string) => {
      if (url === '/settings/me') {
        return Promise.resolve({
          data: {
            llm_provider: 'vllm',
            llm_model: 'qwen3.6-27b-awq',
            llm_ollama_url: 'http://192.0.2.10:8000',
            has_api_key: false,
          },
        });
      }
      if (url === '/settings/vllm/fleet') {
        return Promise.resolve({ data: { nodes: [] } });
      }
      // The vllm models probe hangs — must NOT block the form render
      if (url === '/settings/vllm/models') {
        return new Promise(() => {});
      }
      return Promise.reject(new Error(`unexpected url ${url}`));
    });

    render(<SettingsPage />);

    // The form must appear without waiting for the probe
    await waitFor(() => {
      expect(screen.getByText('llm provider')).toBeInTheDocument();
    });
    expect(screen.getByText('vllm')).toBeInTheDocument();
  });
});
