import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockSwr } = vi.hoisted(() => ({ mockSwr: vi.fn() }));

vi.mock('swr', () => ({
  default: (...args: unknown[]) => mockSwr(...args),
}));

vi.mock('@/lib/api', () => ({
  default: { get: vi.fn() },
}));

import SidecarSelector from '@/components/SidecarSelector';

const SIDECARS = [
  {
    registered_id: 'sidecar-a',
    label: 'Primary',
    capabilities: ['text', 'vision'],
    healthy: true,
    available_slots: 2,
  },
  {
    registered_id: 'sidecar-b',
    label: 'Backup',
    capabilities: ['text'],
    healthy: false,
    available_slots: 0,
  },
];

describe('SidecarSelector', () => {
  beforeEach(() => mockSwr.mockReset());

  it('renders auto plus all registered sidecars from the endpoint', () => {
    mockSwr.mockReturnValue({ data: SIDECARS, error: undefined });
    render(<SidecarSelector value="auto" onChange={() => {}} />);

    const select = screen.getByLabelText('sidecar preference');
    expect(select).toBeEnabled();
    const options = screen.getAllByRole('option');
    expect(options.map((o) => (o as HTMLOptionElement).value)).toEqual([
      'auto',
      'sidecar-a',
      'sidecar-b',
    ]);
    expect(options[0]).toHaveTextContent('auto (default)');
    expect(options[1]).toHaveTextContent(/Primary/);
    expect(options[1]).toHaveTextContent('2 free');
    expect(options[2]).toHaveTextContent(/offline/);
  });

  it('calls onChange with the selected registered id', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    mockSwr.mockReturnValue({ data: SIDECARS, error: undefined });
    render(<SidecarSelector value="auto" onChange={onChange} />);

    await user.selectOptions(screen.getByLabelText('sidecar preference'), 'sidecar-a');
    expect(onChange).toHaveBeenCalledWith('sidecar-a');
  });

  it('disables and falls back to auto-only when the endpoint is unavailable', async () => {
    const onChange = vi.fn();
    mockSwr.mockReturnValue({ data: undefined, error: new Error('network') });
    render(<SidecarSelector value="sidecar-a" onChange={onChange} />);

    const select = screen.getByLabelText('sidecar preference');
    expect(select).toBeDisabled();
    expect(select).toHaveValue('auto');
    expect(screen.getByText(/sidecar selection unavailable/i)).toBeInTheDocument();
    // A stale sidecar id is forced back to auto.
    expect(onChange).toHaveBeenCalledWith('auto');
  });

  it('stays disabled when the parent disables it', () => {
    mockSwr.mockReturnValue({ data: SIDECARS, error: undefined });
    render(<SidecarSelector value="auto" onChange={() => {}} disabled />);
    expect(screen.getByLabelText('sidecar preference')).toBeDisabled();
  });
});
