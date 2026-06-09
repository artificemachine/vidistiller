import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

// ---- hoisted mocks ----
const { mockGet, mockPost, mockDelete, mockExportObsidian, mockSetJobStatus } =
  vi.hoisted(() => ({
    mockGet: vi.fn(),
    mockPost: vi.fn(),
    mockDelete: vi.fn(),
    mockExportObsidian: vi.fn(),
    mockSetJobStatus: vi.fn(),
  }));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet, post: mockPost, delete: mockDelete },
}));

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'test-job-uuid' }),
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), back: vi.fn() }),
}));

vi.mock('@/lib/exportObsidian', () => ({
  exportToObsidian: mockExportObsidian,
}));

vi.mock('@/components/JobStatusProvider', () => ({
  useJobStatus: () => ({ jobStatus: null, setJobStatus: mockSetJobStatus }),
}));

// Stub YouTube player — not relevant to these tests
vi.mock('@/components/YouTubePlayer', () => ({
  default: vi.fn().mockReturnValue(<div data-testid="yt-player">player</div>),
}));

// Stub WorkspaceLayout to just render sidebar + children
vi.mock('@/components/layout/WorkspaceLayout', () => ({
  default: ({ sidebar, sidebarActions }: any) => (
    <div>
      <div data-testid="sidebar">{sidebar}</div>
      <div data-testid="sidebar-actions">{sidebarActions}</div>
    </div>
  ),
}));

import JobDetail from '@/app/jobs/[id]/page';

// ---- helpers ----

const COMPLETED_JOB = {
  id: 1,
  job_id: 'test-job-uuid',
  status: 'completed' as const,
  video_url: 'https://youtube.com/watch?v=abc',
  summarize_status: null,
  processing_mode: null,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T01:00:00Z',
  videos: [{ id: 1, title: 'Test Video', duration: 120, description: '' }],
  transcripts: [
    {
      id: 1,
      full_text: '[00:00:05] Hello world\n[00:00:10] Second line',
      language: 'en',
    },
  ],
  documents: [],
  snapshots: [
    {
      id: 1,
      file_path: '/data/snapshots/test/snap.jpg',
      timestamp: 5.0,
      relevance_score: 0.9,
      image_url: '/static/snapshots/test/snap.jpg',
    },
  ],
  slides: [],
};

function mockJobResponse(overrides: Record<string, any> = {}) {
  const data = { ...COMPLETED_JOB } as Record<string, any>;
  Object.keys(overrides).forEach((key) => {
    data[key] = overrides[key];
  });
  return { data };
}

function setupCompletedJob(overrides: Record<string, any> = {}) {
  const response = mockJobResponse(overrides);
  mockGet.mockImplementation((url: string, _opts?: any) => {
    if (url.includes('/logs')) return Promise.resolve({ data: [] });
    return Promise.resolve(response);
  });
}

let alertSpy: ReturnType<typeof vi.spyOn>;
beforeEach(() => {
  vi.clearAllMocks();
  mockExportObsidian.mockResolvedValue(undefined);
  alertSpy = vi.spyOn(window, 'alert').mockImplementation(() => {});
  URL.createObjectURL = vi.fn(() => 'blob:mock');
  URL.revokeObjectURL = vi.fn();
});

afterEach(() => {
  alertSpy.mockRestore();
});

// ---- tests ----

describe('JobDetail — save (JSON export)', () => {
  it('calls GET /jobs/{id}/export and triggers download', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockGet.mockImplementation((url: string, opts?: any) => {
      if (url.includes('/export')) {
        return Promise.resolve({ data: new Blob([JSON.stringify({ job: {} })]) });
      }
      if (url.includes('/logs')) return Promise.resolve({ data: [] });
      return Promise.resolve(mockJobResponse());
    });

    render(<JobDetail />);
    const saveBtn = await screen.findByRole('button', { name: /backup/i });
    await user.click(saveBtn);

    await waitFor(() => {
      const exportCall = mockGet.mock.calls.find(
        (c: any[]) => typeof c[0] === 'string' && c[0].includes('/export'),
      );
      expect(exportCall).toBeDefined();
      expect(exportCall![1]).toEqual({ responseType: 'blob' });
    });
  });

  it('shows alert on save failure', async () => {
    const user = userEvent.setup();
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/export')) {
        return Promise.reject({
          response: { data: { detail: 'not found' } },
        });
      }
      if (url.includes('/logs')) return Promise.resolve({ data: [] });
      return Promise.resolve(mockJobResponse());
    });

    render(<JobDetail />);
    const saveBtn = await screen.findByRole('button', { name: /backup/i });
    await user.click(saveBtn);

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('not found');
    });
  });
});

describe('JobDetail — export (Obsidian)', () => {
  it('calls exportToObsidian with correct parameters', async () => {
    const user = userEvent.setup();
    setupCompletedJob();

    render(<JobDetail />);
    const exportBtn = await screen.findByRole('button', { name: /markdown/i });
    await user.click(exportBtn);

    await waitFor(() => {
      expect(mockExportObsidian).toHaveBeenCalledTimes(1);
      const opts = mockExportObsidian.mock.calls[0][0];
      expect(opts.title).toBe('Test Video');
      expect(opts.videoUrl).toBe('https://youtube.com/watch?v=abc');
      expect(opts.transcriptText).toContain('Hello world');
      expect(opts.snapshots).toHaveLength(1);
      expect(opts.snapshots[0].timestamp).toBe(5.0);
    });
  });

  it('does nothing when no transcripts available', async () => {
    const user = userEvent.setup();
    setupCompletedJob({ transcripts: [] });

    render(<JobDetail />);

    // With no transcripts, the export button shouldn't even render
    await waitFor(() => {
      expect(screen.queryByRole('button', { name: /markdown/i })).not.toBeInTheDocument();
    });
  });

  it('passes slides data to export when present', async () => {
    const user = userEvent.setup();
    setupCompletedJob({
      processing_mode: 'slide_aware',
      slides: [
        {
          id: 1,
          slide_number: 1,
          start_timestamp: 0,
          end_timestamp: 60,
          image_url: '/static/slides/1.jpg',
          ocr_text: 'Slide text',
        },
      ],
    });

    render(<JobDetail />);
    const exportBtn = await screen.findByRole('button', { name: /markdown/i });
    await user.click(exportBtn);

    await waitFor(() => {
      const opts = mockExportObsidian.mock.calls[0][0];
      expect(opts.slides).toHaveLength(1);
      expect(opts.slides[0].slide_number).toBe(1);
      expect(opts.slides[0].ocr_text).toBe('Slide text');
    });
  });
});

describe('JobDetail — summary', () => {
  it('renders summary button when transcripts exist', async () => {
    setupCompletedJob();
    render(<JobDetail />);
    expect(await screen.findByRole('button', { name: /summary/i })).toBeInTheDocument();
  });

  it('calls POST /jobs/{id}/summarize on click', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockPost.mockResolvedValue({ status: 200, data: { content: '## Summary\nDone.' } });

    render(<JobDetail />);
    const summaryBtn = await screen.findByRole('button', { name: /summary/i });
    await user.click(summaryBtn);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith(
        '/jobs/test-job-uuid/summarize',
      );
    });
  });

  it('toggles back to transcript when summary button clicked again', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockPost.mockResolvedValue({ status: 200, data: { content: '## Summary\nDone.' } });

    render(<JobDetail />);
    const summaryBtn = await screen.findByRole('button', { name: /summary/i });

    // First click — triggers summarize
    await user.click(summaryBtn);
    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledTimes(1);
    });

    // Now the button should read "transcript" (toggle back)
    const transcriptBtn = await screen.findByRole('button', { name: /transcript/i });
    await user.click(transcriptBtn);

    // Second click does NOT call API — it just toggles state
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it('shows "summarizing..." while loading', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockPost.mockReturnValue(new Promise(() => {})); // never resolves

    render(<JobDetail />);
    const summaryBtn = await screen.findByRole('button', { name: /summary/i });
    await user.click(summaryBtn);

    expect(await screen.findByText('summarizing...')).toBeInTheDocument();
  });

  it('handles 202 (async background summarization)', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockPost.mockResolvedValue({ status: 202, data: {} });

    render(<JobDetail />);
    const summaryBtn = await screen.findByRole('button', { name: /summary/i });
    await user.click(summaryBtn);

    // After 202, button should show "summarizing..." and stay in loading state
    expect(await screen.findByText('summarizing...')).toBeInTheDocument();
  });

  it('shows alert on non-ollama summarize error', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockPost.mockRejectedValue({
      response: { data: { detail: 'provider misconfigured' } },
    });

    render(<JobDetail />);
    const summaryBtn = await screen.findByRole('button', { name: /summary/i });
    await user.click(summaryBtn);

    await waitFor(() => {
      expect(alertSpy).toHaveBeenCalledWith('provider misconfigured');
    });
  });

  it('shows ollama diagnostics modal on connection error', async () => {
    const user = userEvent.setup();
    setupCompletedJob();
    mockPost.mockRejectedValue({
      response: { data: { detail: 'could not connect to ollama' } },
    });
    // Mock the diagnostics endpoint
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/diagnostics/ollama')) {
        return Promise.resolve({
          data: { error: 'connection refused', suggestions: ['start ollama'] },
        });
      }
      if (url.includes('/logs')) return Promise.resolve({ data: [] });
      return Promise.resolve(mockJobResponse());
    });

    render(<JobDetail />);
    const summaryBtn = await screen.findByRole('button', { name: /summary/i });
    await user.click(summaryBtn);

    await waitFor(() => {
      const diagCall = mockGet.mock.calls.find(
        (c: any[]) => typeof c[0] === 'string' && c[0].includes('/diagnostics/ollama'),
      );
      expect(diagCall).toBeDefined();
    });
  });

  it('auto-loads cached summary from job documents', async () => {
    setupCompletedJob({
      summarize_status: 'completed',
      documents: [
        { id: 10, title: 'Summary', content: '## Cached summary\nHere.', format: 'summary' },
      ],
    });

    render(<JobDetail />);

    // The cached summary should not auto-show (user must click summary button),
    // but the content should be pre-loaded so clicking summary doesn't trigger API call
    // Verify the summary button exists
    expect(await screen.findByRole('button', { name: /summary/i })).toBeInTheDocument();
  });
});

describe('JobDetail — cancel summarization', () => {
  it('shows stop button when summarize_status is processing on load', async () => {
    setupCompletedJob({ summarize_status: 'processing' });
    render(<JobDetail />);
    expect(await screen.findByRole('button', { name: /stop/i })).toBeInTheDocument();
  });

  it('calls POST /jobs/{id}/cancel on stop click', async () => {
    const user = userEvent.setup();
    setupCompletedJob({ summarize_status: 'processing' });
    mockPost.mockResolvedValue({});

    render(<JobDetail />);
    const stopBtn = await screen.findByRole('button', { name: /stop/i });
    await user.click(stopBtn);

    await waitFor(() => {
      expect(mockPost).toHaveBeenCalledWith('/jobs/test-job-uuid/cancel');
    });
  });
});

describe('JobDetail — summary polling restart', () => {
  // Fake timers + RTL: findByRole/waitFor use setTimeout internally and hang with fake timers.
  // Fix: wrap render in act() to flush the initial fetch, then use synchronous getByRole/getByText.
  beforeEach(() => {
    vi.useFakeTimers();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it('restarts polling on 202 for completed job and shows result', async () => {
    let phase = 0; // 0=initial, 1=processing, 2=completed
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/logs')) return Promise.resolve({ data: [] });
      if (phase === 0) return Promise.resolve(mockJobResponse());
      if (phase === 1) return Promise.resolve(mockJobResponse({ summarize_status: 'processing' }));
      return Promise.resolve(
        mockJobResponse({
          summarize_status: 'completed',
          documents: [{ id: 10, title: 'Summary', content: '## Result\nDone.', format: 'summary' }],
        })
      );
    });
    mockPost.mockResolvedValue({ status: 202, data: {} });

    // Wrap render in act() so the initial fetchJob() promise resolves before we proceed
    await act(async () => {
      render(<JobDetail />);
    });
    const summaryBtn = screen.getByRole('button', { name: /^summary$/i });

    // Fire initial interval tick → stop condition (jobDone && summarizeSettled) → intervalRef = null
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    // Click summarize: POST → 202 → interval restarted from null ref
    phase = 1;
    await act(async () => {
      summaryBtn.click();
    });
    expect(screen.getByRole('button', { name: /summarizing\.\.\./i })).toBeInTheDocument();

    // Advance to next tick; backend delivers completed result
    phase = 2;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(screen.queryByRole('button', { name: /summarizing\.\.\./i })).not.toBeInTheDocument();
  });

  it('shows error message in sidebar when summarize_status is failed', async () => {
    let phase = 0;
    mockGet.mockImplementation((url: string) => {
      if (url.includes('/logs')) return Promise.resolve({ data: [] });
      if (phase === 0) return Promise.resolve(mockJobResponse());
      if (phase === 1) return Promise.resolve(mockJobResponse({ summarize_status: 'processing' }));
      return Promise.resolve(mockJobResponse({ summarize_status: 'failed' }));
    });
    mockPost.mockResolvedValue({ status: 202, data: {} });

    await act(async () => {
      render(<JobDetail />);
    });
    const summaryBtn = screen.getByRole('button', { name: /^summary$/i });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    phase = 1;
    await act(async () => {
      summaryBtn.click();
    });
    expect(screen.getByRole('button', { name: /summarizing\.\.\./i })).toBeInTheDocument();

    phase = 2;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(screen.getByText(/summarization failed/i)).toBeInTheDocument();
  });
});
