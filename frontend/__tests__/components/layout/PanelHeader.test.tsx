import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import PanelHeader from '@/components/layout/PanelHeader';

describe('PanelHeader', () => {
  it('renders the title', () => {
    render(<PanelHeader title="Transcript" />);
    expect(screen.getByText('Transcript')).toBeInTheDocument();
  });

  it('does not render collapse button without onToggleCollapse', () => {
    render(<PanelHeader title="Player" />);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('renders collapse button when onToggleCollapse is provided', () => {
    const handler = vi.fn();
    render(<PanelHeader title="Snapshots" onToggleCollapse={handler} />);
    expect(screen.getByRole('button')).toBeInTheDocument();
  });

  it('calls onToggleCollapse when button is clicked', async () => {
    const user = userEvent.setup();
    const handler = vi.fn();
    render(<PanelHeader title="Sidebar" onToggleCollapse={handler} />);

    await user.click(screen.getByRole('button'));
    expect(handler).toHaveBeenCalledOnce();
  });
});
