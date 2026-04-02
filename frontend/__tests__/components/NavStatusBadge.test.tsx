import React, { useEffect } from 'react';
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import JobStatusProvider, { useJobStatus } from '@/components/JobStatusProvider';
import NavStatusBadge from '@/components/NavStatusBadge';

function TestHarness({ status }: { status: 'pending' | 'processing' | 'completed' | 'failed' | null }) {
  const { setJobStatus } = useJobStatus();
  useEffect(() => { setJobStatus(status); }, [status, setJobStatus]);
  return <NavStatusBadge />;
}

function renderBadge(status: 'pending' | 'processing' | 'completed' | 'failed' | null) {
  return render(
    <JobStatusProvider>
      <TestHarness status={status} />
    </JobStatusProvider>
  );
}

describe('NavStatusBadge', () => {
  it('renders nothing when jobStatus is null', () => {
    const { container } = render(
      <JobStatusProvider>
        <NavStatusBadge />
      </JobStatusProvider>
    );
    expect(container.querySelector('span')).toBeNull();
  });

  it('renders "complete" badge for completed status', () => {
    renderBadge('completed');
    expect(screen.getByText('complete')).toBeInTheDocument();
  });

  it('renders "processing" badge for processing status', () => {
    renderBadge('processing');
    expect(screen.getByText('processing')).toBeInTheDocument();
  });

  it('renders "failed" badge for failed status', () => {
    renderBadge('failed');
    expect(screen.getByText('failed')).toBeInTheDocument();
  });

  it('renders "pending" badge for pending status', () => {
    renderBadge('pending');
    expect(screen.getByText('pending')).toBeInTheDocument();
  });

  it('applies green styling for completed status', () => {
    renderBadge('completed');
    const badge = screen.getByText('complete');
    expect(badge.className).toContain('bg-green-100');
    expect(badge.className).toContain('text-green-800');
  });

  it('applies red styling for failed status', () => {
    renderBadge('failed');
    const badge = screen.getByText('failed');
    expect(badge.className).toContain('bg-red-100');
    expect(badge.className).toContain('text-red-800');
  });
});
