import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet, mockPost, mockPush } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPush: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet, post: mockPost },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush, replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

vi.mock('@/lib/authStore', () => ({
  useAuthStore: () => ({ isAuthenticated: true, isLoading: false }),
}));

import Home from '@/app/page';

beforeEach(() => {
  vi.clearAllMocks();
  mockGet.mockResolvedValue({ data: [] });
});

describe('Home — import job', () => {
  it('renders the import section collapsed by default', () => {
    render(<Home />);
    expect(screen.getByText(/have an exported .json\? import it/i)).toBeInTheDocument();
    // The import button should exist inside the details but be disabled (no file selected)
    expect(screen.getByRole('button', { name: /import job/i })).toBeDisabled();
  });

  it('disables the import button when no file is selected', () => {
    render(<Home />);
    expect(screen.getByRole('button', { name: /import job/i })).toBeDisabled();
  });

  it('enables the import button after selecting a file', async () => {
    const user = userEvent.setup();
    render(<Home />);

    const file = new File(
      [JSON.stringify({ export_version: '1.0', job: {} })],
      'export.json',
      { type: 'application/json' },
    );
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, file);

    expect(screen.getByRole('button', { name: /import job/i })).toBeEnabled();
  });

  it('calls POST /jobs/import and navigates on success', async () => {
    const user = userEvent.setup();
    const payload = { export_version: '1.0', job: { job_id: 'abc-123' } };
    mockPost.mockResolvedValue({ data: { job_id: 'abc-123' } });

    render(<Home />);

    // Open the collapsed <details> section
    await user.click(screen.getByText(/have an exported .json\? import it/i));

    const jsonStr = JSON.stringify(payload);
    const file = new File([jsonStr], 'export.json', { type: 'application/json' });
    // Ensure File.text() works in jsdom
    file.text = vi.fn().mockResolvedValue(jsonStr);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, file);
    await user.click(screen.getByRole('button', { name: /import job/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/jobs/import', payload);
    });
    expect(mockPush).toHaveBeenCalledWith('/jobs/abc-123');
  });

  it('shows error when import API fails', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValue({
      response: { data: { detail: 'duplicate video_id' } },
    });

    render(<Home />);
    await user.click(screen.getByText(/have an exported .json\? import it/i));

    const jsonStr = JSON.stringify({ job: {} });
    const file = new File([jsonStr], 'bad.json', { type: 'application/json' });
    file.text = vi.fn().mockResolvedValue(jsonStr);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, file);
    await user.click(screen.getByRole('button', { name: /import job/i }));

    expect(await screen.findByText('duplicate video_id')).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('shows generic error on invalid JSON file', async () => {
    const user = userEvent.setup();
    render(<Home />);
    await user.click(screen.getByText(/have an exported .json\? import it/i));

    const file = new File(['not-json'], 'broken.json', { type: 'application/json' });
    file.text = vi.fn().mockResolvedValue('not-json');

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, file);
    await user.click(screen.getByRole('button', { name: /import job/i }));

    expect(
      await screen.findByText(/failed to import job/i),
    ).toBeInTheDocument();
  });

  it('shows "importing..." text while request is in flight', async () => {
    const user = userEvent.setup();
    // Never resolve — keep it pending
    mockPost.mockReturnValue(new Promise(() => {}));

    render(<Home />);
    await user.click(screen.getByText(/have an exported .json\? import it/i));

    const jsonStr = JSON.stringify({ job: {} });
    const file = new File([jsonStr], 'x.json', { type: 'application/json' });
    file.text = vi.fn().mockResolvedValue(jsonStr);

    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    await user.upload(input, file);
    await user.click(screen.getByRole('button', { name: /import job/i }));

    expect(await screen.findByText('importing...')).toBeInTheDocument();
  });
});

describe('Home — slide mode toggle', () => {
  it('defaults to transcript mode (is_slide_mode off)', () => {
    render(<Home />);
    // "transcript mode" button is the default active selection
    expect(screen.getByRole('button', { name: /transcript mode/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /presentation mode/i })).toBeInTheDocument();
  });

  it('sends is_slide_mode: true when presentation mode is selected', async () => {
    const user = userEvent.setup();
    mockPost.mockResolvedValue({ data: { job_id: 'slide-job-1' } });

    render(<Home />);

    const urlInput = document.querySelector('input[type="url"]') as HTMLInputElement;
    await user.type(urlInput, 'https://youtube.com/watch?v=abc');

    await user.click(screen.getByRole('button', { name: /presentation mode/i }));
    await user.click(screen.getByRole('button', { name: /create document/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/jobs',
        expect.objectContaining({ is_slide_mode: true }),
      );
    });
  });

  it('sends is_slide_mode: false when transcript mode is selected (default)', async () => {
    const user = userEvent.setup();
    mockPost.mockResolvedValue({ data: { job_id: 'transcript-job-1' } });

    render(<Home />);

    const urlInput = document.querySelector('input[type="url"]') as HTMLInputElement;
    await user.type(urlInput, 'https://youtube.com/watch?v=def');

    await user.click(screen.getByRole('button', { name: /create document/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/jobs',
        expect.objectContaining({ is_slide_mode: false }),
      );
    });
  });
});

describe('Home — caption language', () => {
  it('shows a language dropdown once tracks are fetched for a YouTube URL', async () => {
    const user = userEvent.setup();
    mockPost.mockResolvedValue({
      data: {
        video_id: 'abc',
        tracks: [
          { language_code: 'ar', language_name: 'Arabic', is_generated: false },
          { language_code: 'en', language_name: 'English', is_generated: true },
        ],
      },
    });

    render(<Home />);
    const urlInput = document.querySelector('input[type="url"]') as HTMLInputElement;
    await user.type(urlInput, 'https://youtu.be/abc');

    const select = await screen.findByLabelText(/caption language/i);
    expect(select).toBeInTheDocument();
    expect(screen.getByRole('option', { name: /Arabic/i })).toBeInTheDocument();
  });

  it('sends the chosen caption_language when a track is selected', async () => {
    const user = userEvent.setup();
    mockPost.mockImplementation((path: string) => {
      if (path === '/videos/caption-tracks') {
        return Promise.resolve({
          data: { video_id: 'abc', tracks: [{ language_code: 'en', language_name: 'English', is_generated: true }] },
        });
      }
      return Promise.resolve({ data: { job_id: 'lang-job-1' } });
    });

    render(<Home />);
    const urlInput = document.querySelector('input[type="url"]') as HTMLInputElement;
    await user.type(urlInput, 'https://youtu.be/abc');

    const select = await screen.findByLabelText(/caption language/i);
    await user.selectOptions(select, 'en');
    await user.click(screen.getByRole('button', { name: /create document/i }));

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/jobs',
        expect.objectContaining({ caption_language: 'en' }),
      );
    });
  });

  it('omits caption_language when left on auto', async () => {
    const user = userEvent.setup();
    mockPost.mockImplementation((path: string) => {
      if (path === '/videos/caption-tracks') {
        return Promise.resolve({ data: { video_id: 'abc', tracks: [] } });
      }
      return Promise.resolve({ data: { job_id: 'auto-job-1' } });
    });

    render(<Home />);
    const urlInput = document.querySelector('input[type="url"]') as HTMLInputElement;
    await user.type(urlInput, 'https://youtube.com/watch?v=xyz');
    await user.click(screen.getByRole('button', { name: /create document/i }));

    await waitFor(() => {
      const jobCall = mockPost.mock.calls.find((c) => c[0] === '/jobs');
      expect(jobCall).toBeTruthy();
      expect(jobCall![1]).not.toHaveProperty('caption_language');
    });
  });
});
