import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
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

  it('preview uses the backend-captured dimensions (portrait not forced to 16:9)', () => {
    const portrait = [{ id: 1, image_url: '/s/p.jpg', timestamp: 10, image_width: 1080, image_height: 1920 }];
    render(<SnapshotsGallery snapshots={portrait} />);
    const box = (screen.getByAltText('snapshot at 0:10') as HTMLImageElement).parentElement as HTMLElement;
    // Set from backend dims immediately, before the image ever loads.
    expect(box.style.aspectRatio).toBe('1080/1920');
  });

  it('falls back to the loaded image natural aspect ratio when backend dims are absent', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} />);
    const preview = screen.getByAltText('snapshot at 0:10') as HTMLImageElement;
    const box = preview.parentElement as HTMLElement;
    expect(box.style.aspectRatio).toBe('16/9'); // no dims yet, no load
    Object.defineProperty(preview, 'naturalWidth', { value: 1080, configurable: true });
    Object.defineProperty(preview, 'naturalHeight', { value: 1920, configurable: true });
    fireEvent.load(preview);
    expect(box.style.aspectRatio).toBe('1080/1920');
  });

  it('thumbnails use object-contain so portrait frames are not cropped', () => {
    render(<SnapshotsGallery snapshots={mockSnapshots} />);
    const thumbImgs = screen
      .getAllByRole('button')
      .map((b) => b.querySelector('img'))
      .filter((img): img is HTMLImageElement => img !== null);
    expect(thumbImgs.length).toBe(3);
    thumbImgs.forEach((img) => expect(img.className).toContain('object-contain'));
  });
});
