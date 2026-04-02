import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import SlidesGallery from '@/components/SlidesGallery';

const mockSlides = [
  {
    id: 1,
    slide_number: 1,
    start_timestamp: 0,
    end_timestamp: 60,
    image_url: '/static/slides/job1/slide_001.jpg',
    ocr_text: 'Title Slide Content',
    transcript_text: 'Welcome to the presentation',
    is_incremental_build: false,
  },
  {
    id: 2,
    slide_number: 2,
    start_timestamp: 60,
    end_timestamp: 120,
    image_url: '/static/slides/job1/slide_002.jpg',
    ocr_text: 'Main Content',
    transcript_text: 'Here is the main content',
    is_incremental_build: false,
  },
  {
    id: 3,
    slide_number: 3,
    start_timestamp: 120,
    end_timestamp: 180,
    image_url: '/static/slides/job1/slide_003.jpg',
    ocr_text: null,
    transcript_text: null,
    is_incremental_build: true,
  },
];

describe('SlidesGallery', () => {
  it('renders empty state when no slides', () => {
    render(<SlidesGallery slides={[]} />);
    expect(screen.getByText(/no slides detected/i)).toBeInTheDocument();
  });

  it('renders slide count and thumbnails', () => {
    render(<SlidesGallery slides={mockSlides} />);
    expect(screen.getByText('detected slides (3)')).toBeInTheDocument();
    expect(screen.getAllByRole('button').length).toBeGreaterThanOrEqual(3);
  });

  it('shows first slide as preview by default', () => {
    render(<SlidesGallery slides={mockSlides} />);
    // Both main preview and thumbnail have alt="slide 1"
    const images = screen.getAllByAltText('slide 1');
    expect(images.length).toBeGreaterThanOrEqual(1);
  });

  it('shows slide number badge on preview', () => {
    render(<SlidesGallery slides={mockSlides} />);
    expect(screen.getByText('slide 1')).toBeInTheDocument();
  });

  it('shows timestamp range for selected slide', () => {
    render(<SlidesGallery slides={mockSlides} />);
    expect(screen.getByText('0:00 - 1:00')).toBeInTheDocument();
  });

  it('calls onSlideClick when thumbnail is clicked', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<SlidesGallery slides={mockSlides} onSlideClick={onClick} />);

    const thumbnails = screen.getAllByRole('button').filter(
      (btn) => btn.querySelector('img') || btn.querySelector('span')
    );
    // Click the second slide thumbnail
    await user.click(thumbnails[1]);
    expect(onClick).toHaveBeenCalledWith(mockSlides[1]);
  });

  it('shows OCR text when "show text" is clicked', async () => {
    const user = userEvent.setup();
    render(<SlidesGallery slides={mockSlides} />);

    const showTextBtn = screen.getByText('show text');
    await user.click(showTextBtn);

    expect(screen.getByText('ocr text')).toBeInTheDocument();
    expect(screen.getByText('Title Slide Content')).toBeInTheDocument();
    expect(screen.getByText('transcript')).toBeInTheDocument();
    expect(screen.getByText('Welcome to the presentation')).toBeInTheDocument();
  });

  it('toggles text visibility', async () => {
    const user = userEvent.setup();
    render(<SlidesGallery slides={mockSlides} />);

    await user.click(screen.getByText('show text'));
    expect(screen.getByText('hide text')).toBeInTheDocument();

    await user.click(screen.getByText('hide text'));
    expect(screen.getByText('show text')).toBeInTheDocument();
  });

  it('calls onSelectedIndexChange when thumbnail is clicked', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<SlidesGallery slides={mockSlides} onSelectedIndexChange={onChange} />);

    const thumbnails = screen.getAllByRole('button').filter(
      (btn) => btn.querySelector('img') || btn.querySelector('span')
    );
    await user.click(thumbnails[2]);
    expect(onChange).toHaveBeenCalledWith(2);
  });
});
