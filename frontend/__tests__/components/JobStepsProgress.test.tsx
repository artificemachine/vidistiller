import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';
import JobStepsProgress, { type JobStep } from '@/components/JobStepsProgress';

const steps: JobStep[] = [
  { name: 'summarize', status: 'failed', attempt: 2, percent: 45, error_message: 'model unavailable' },
  { name: 'download', status: 'completed', attempt: 1, percent: 100 },
  { name: 'transcribe', status: 'running', attempt: 1, percent: 20, started_at: '2026-08-12T10:00:00Z' },
];

describe('JobStepsProgress', () => {
  it('renders steps in canonical order', () => {
    render(<JobStepsProgress steps={steps} />);
    const labels = screen.getAllByTestId('job-step-name').map((node) => node.textContent);
    expect(labels).toEqual(['download', 'transcribe', 'summarize']);
  });

  it('renders attempt, percent, timestamps and error', () => {
    render(<JobStepsProgress steps={steps} />);
    expect(screen.getByText('attempt 2 · 45%')).toBeInTheDocument();
    expect(screen.getByText('model unavailable')).toBeInTheDocument();
    expect(screen.getByText(/started 2026/)).toBeInTheDocument();
  });

  it('shows retry only for a failed step', () => {
    const retry = vi.fn();
    render(<JobStepsProgress steps={steps} onRetry={retry} />);
    fireEvent.click(screen.getByRole('button', { name: 'Retry summarize' }));
    expect(retry).toHaveBeenCalledWith('summarize');
    expect(screen.queryByRole('button', { name: 'Retry download' })).not.toBeInTheDocument();
  });

  it('does not invent progress when steps are empty', () => {
    const { container } = render(<JobStepsProgress steps={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders overall progress and ETA range when present', () => {
    render(
      <JobStepsProgress
        steps={[]}
        overallProgress={64}
        eta={{ eta_low_seconds: 120, eta_high_seconds: 360, confidence: 0.82 }}
      />
    );
    expect(screen.getByTestId('overall-progress')).toHaveTextContent('64%');
    expect(screen.getByTestId('eta-range')).toHaveTextContent('eta 2m–6m');
    expect(screen.getByTestId('eta-range')).toHaveTextContent('high confidence');
  });

  it('renders nothing extra when overall progress and eta are absent', () => {
    render(<JobStepsProgress steps={[]} overallProgress={null} eta={undefined} />);
    expect(screen.queryByTestId('overall-progress')).not.toBeInTheDocument();
    expect(screen.queryByTestId('eta-range')).not.toBeInTheDocument();
  });
});
