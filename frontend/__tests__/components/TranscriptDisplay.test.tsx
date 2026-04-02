import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import TranscriptDisplay from '@/components/TranscriptDisplay';

const segments = [
  { id: '1', text: 'Hello world', start_time: 0, end_time: 5 },
  { id: '2', text: 'Setting up React', start_time: 10, end_time: 20, speaker: 'Alice' },
  { id: '3', text: 'Installing dependencies', start_time: 65, end_time: 80 },
];

describe('TranscriptDisplay', () => {
  it('renders all segments', () => {
    render(<TranscriptDisplay segments={segments} />);
    expect(screen.getByText('Hello world')).toBeInTheDocument();
    expect(screen.getByText('Setting up React')).toBeInTheDocument();
    expect(screen.getByText('Installing dependencies')).toBeInTheDocument();
  });

  it('renders speaker name when provided', () => {
    render(<TranscriptDisplay segments={segments} />);
    expect(screen.getByText('Alice')).toBeInTheDocument();
  });

  it('formats timestamps correctly', () => {
    render(<TranscriptDisplay segments={segments} />);
    expect(screen.getByText('0:00')).toBeInTheDocument();
    expect(screen.getByText('0:10')).toBeInTheDocument();
    expect(screen.getByText('1:05')).toBeInTheDocument();
  });

  it('filters segments by search term', async () => {
    const user = userEvent.setup();
    render(<TranscriptDisplay segments={segments} />);

    const search = screen.getByPlaceholderText('search transcript...');
    await user.type(search, 'React');

    expect(screen.getByText('Setting up React')).toBeInTheDocument();
    expect(screen.queryByText('Hello world')).not.toBeInTheDocument();
    expect(screen.queryByText('Installing dependencies')).not.toBeInTheDocument();
  });

  it('calls onTimestampClick with correct seconds when timestamp is clicked', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(<TranscriptDisplay segments={segments} onTimestampClick={handler} />);

    await user.click(screen.getByText('1:05'));
    expect(handler).toHaveBeenCalledWith(65);
  });

  it('does not crash when onTimestampClick is not provided', async () => {
    const user = userEvent.setup();
    render(<TranscriptDisplay segments={segments} />);

    // Should not throw
    await user.click(screen.getByText('0:10'));
  });
});
