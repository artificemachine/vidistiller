import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SnapshotsGallery from '@/components/SnapshotsGallery';

const mockSnapshots = [
  { id: 1, image_url: '/static/snapshots/job1/snapshot_10.00s.jpg', timestamp: 10, detected_text: 'hello' },
  { id: 2, image_url: '/static/snapshots/job1/snapshot_30.00s.jpg', timestamp: 30 },
  { id: 3, image_url: '/static/snapshots/job1/snapshot_60.00s.jpg', timestamp: 60 },
];

describe('SnapshotsGallery', () => {
  it('renders empty state when no snapshots', () => {
    render(<SnapshotsGallery snapshots={[]} />);
    expect(screen.getByText(/no snapshots captured/i)).toBeInTheDocument();
  });

  it('renders snapshot count and thumbnails', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} />);
    expect(screen.getByText('captured snapshots (3)')).toBeInTheDocument();
    expect(screen.getAllByRole('button')).toHaveLength(3); // 3 thumbnails
  });

  it('shows first snapshot as preview by default', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} />);
    const preview = screen.getByAltText('snapshot at 0:10');
    expect(preview).toBeInTheDocument();
  });

  it('selects last snapshot when externalSelectedIndex is -1', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} externalSelectedIndex={-1} />);
    const preview = screen.getByAltText('snapshot at 1:00');
    expect(preview).toBeInTheDocument();
  });

  it('selects specific snapshot via externalSelectedIndex', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} externalSelectedIndex={1} />);
    const preview = screen.getByAltText('snapshot at 0:30');
    expect(preview).toBeInTheDocument();
  });

  it('calls onSelectedIndexChange when thumbnail is clicked', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SnapshotsGallery snapshots={mockSnapshots} onSelectedIndexChange={onChange} />);

    const thumbnails = screen.getAllByRole('button');
    await user.click(thumbnails[2]); // click third thumbnail
    expect(onChange).toHaveBeenCalledWith(2);
  });

  it('calls onDelete when delete button is clicked', async () => {
    const user = userEvent.setup();
    const onDelete = vi.fn();
    render(<SnapshotsGallery snapshots={mockSnapshots} onDelete={onDelete} />);

    const deleteButtons = screen.getAllByTitle('delete snapshot');
    await user.click(deleteButtons[0]);
    expect(onDelete).toHaveBeenCalledWith(1);
  });

  it('clamps externalSelectedIndex to array bounds', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} externalSelectedIndex={99} />);
    // Should clamp to last item
    const preview = screen.getByAltText('snapshot at 1:00');
    expect(preview).toBeInTheDocument();
  });
});
