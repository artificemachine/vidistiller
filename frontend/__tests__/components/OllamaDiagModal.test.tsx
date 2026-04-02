import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import OllamaDiagModal from '@/components/OllamaDiagModal';

const unreachableDiag = {
  url: 'http://localhost:11434',
  model: 'qwen3:8b',
  reachable: false,
  response_time_ms: 0,
  models_available: [],
  model_found: false,
  error: 'Connection refused',
  suggestions: [
    'Run: ollama serve',
    'Check OLLAMA_URL is correct (currently: http://localhost:11434)',
    'Check firewall / network',
  ],
};

const modelMissingDiag = {
  url: 'http://localhost:11434',
  model: 'qwen3:8b',
  reachable: true,
  response_time_ms: 42,
  models_available: ['mistral:latest', 'codellama:7b'],
  model_found: false,
  error: null,
  suggestions: [
    'Run: ollama pull qwen3:8b',
    'Or set OLLAMA_MODEL to one of: mistral:latest, codellama:7b',
  ],
};

const healthyDiag = {
  url: 'http://localhost:11434',
  model: 'qwen3:8b',
  reachable: true,
  response_time_ms: 15,
  models_available: ['qwen3:8b', 'mistral:latest'],
  model_found: true,
  error: null,
  suggestions: ['Check Ollama logs: journalctl -u ollama'],
};

describe('OllamaDiagModal', () => {
  it('renders header', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.getByText('ollama not available')).toBeInTheDocument();
  });

  it('shows red status when unreachable', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.getByText('not reachable')).toBeInTheDocument();
    const dot = screen.getByTestId('status-dot');
    expect(dot.className).toContain('bg-red-500');
  });

  it('shows green status when reachable', () => {
    render(<OllamaDiagModal diag={modelMissingDiag} onDismiss={() => {}} />);
    expect(screen.getByText('connected')).toBeInTheDocument();
    const dot = screen.getByTestId('status-dot');
    expect(dot.className).toContain('bg-green-500');
  });

  it('displays configured URL and model', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.getByText('http://localhost:11434')).toBeInTheDocument();
    expect(screen.getByText('qwen3:8b')).toBeInTheDocument();
  });

  it('shows error message when present', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.getByText('Connection refused')).toBeInTheDocument();
  });

  it('does not show error when null', () => {
    render(<OllamaDiagModal diag={modelMissingDiag} onDismiss={() => {}} />);
    expect(screen.queryByText('Connection refused')).not.toBeInTheDocument();
  });

  it('shows response time when reachable', () => {
    render(<OllamaDiagModal diag={modelMissingDiag} onDismiss={() => {}} />);
    expect(screen.getByText('42ms')).toBeInTheDocument();
  });

  it('hides response time when unreachable', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.queryByText('0ms')).not.toBeInTheDocument();
  });

  it('lists available models when reachable', () => {
    render(<OllamaDiagModal diag={modelMissingDiag} onDismiss={() => {}} />);
    expect(screen.getByText('mistral:latest')).toBeInTheDocument();
    expect(screen.getByText('codellama:7b')).toBeInTheDocument();
  });

  it('hides available models section when unreachable', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.queryByText('available models:')).not.toBeInTheDocument();
  });

  it('renders numbered suggestions', () => {
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={() => {}} />);
    expect(screen.getByText('suggestions:')).toBeInTheDocument();
    expect(screen.getByText('Run: ollama serve')).toBeInTheDocument();
    expect(screen.getByText('Check firewall / network')).toBeInTheDocument();
  });

  it('calls onDismiss when Dismiss button is clicked', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(<OllamaDiagModal diag={unreachableDiag} onDismiss={handler} />);

    await user.click(screen.getByText('dismiss'));
    expect(handler).toHaveBeenCalledOnce();
  });

  it('renders correctly for healthy state', () => {
    render(<OllamaDiagModal diag={healthyDiag} onDismiss={() => {}} />);
    expect(screen.getByText('connected')).toBeInTheDocument();
    // qwen3:8b appears in both Model field and Available models list
    expect(screen.getAllByText('qwen3:8b')).toHaveLength(2);
    expect(screen.getByText('15ms')).toBeInTheDocument();
    expect(screen.getByText('Check Ollama logs: journalctl -u ollama')).toBeInTheDocument();
  });
});
