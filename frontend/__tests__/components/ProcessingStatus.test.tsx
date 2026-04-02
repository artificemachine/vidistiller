import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import ProcessingStatus from '@/components/ProcessingStatus';

describe('ProcessingStatus', () => {
  it('renders pending status', () => {
    render(<ProcessingStatus status="pending" />);
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('renders completed status', () => {
    render(<ProcessingStatus status="completed" />);
    expect(screen.getByText('completed')).toBeInTheDocument();
  });

  it('renders failed status', () => {
    render(<ProcessingStatus status="failed" />);
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('renders message when provided', () => {
    render(<ProcessingStatus status="processing" message="Working on it..." />);
    expect(screen.getByText('Working on it...')).toBeInTheDocument();
  });

  it('shows progress bar when processing', () => {
    render(<ProcessingStatus status="processing" progress={42} />);
    expect(screen.getByText('42%')).toBeInTheDocument();
  });

  it('does not show progress bar when not processing', () => {
    render(<ProcessingStatus status="completed" progress={100} />);
    expect(screen.queryByText('progress')).not.toBeInTheDocument();
  });
});
