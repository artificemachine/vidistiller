import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

// SidecarSelector is rendered inside the form; keep its data fetch deterministic.
vi.mock('@/lib/api', () => ({
  default: { get: vi.fn() },
}));
vi.mock('swr', () => ({
  default: () => ({ data: [], error: undefined }),
}));

import VideoSubmission from '@/components/VideoSubmission';

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

describe('VideoSubmission', () => {
  beforeEach(() => {
    mockPush.mockReset();
    global.fetch = vi.fn();
  });

  const fillAndSubmit = async (url: string) => {
    const user = userEvent.setup();
    render(<VideoSubmission />);
    const input = screen.getByPlaceholderText(/YouTube, Vimeo/i);
    await user.type(input, url);
    await user.click(screen.getByRole('button', { name: /convert to documentation/i }));
  };

  it('navigates to the job on successful creation', async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(201, { job_id: 'job-123', status: 'pending' })
    );

    await fillAndSubmit('https://www.youtube.com/watch?v=dQw4w9WgXcQ');

    expect(mockPush).toHaveBeenCalledWith('/jobs/job-123');
  });

  it('shows a duplicate warning on 409 instead of navigating', async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(409, {
        error: 'DUPLICATE_RESOURCE',
        message: 'A job for this video already exists',
        existing_job: {
          job_id: 'job-existing',
          status: 'completed',
          created_at: '2026-08-01T00:00:00Z',
          video_title: 'Existing Video',
        },
      })
    );

    await fillAndSubmit('https://www.youtube.com/watch?v=dQw4w9WgXcQ');

    expect(await screen.findByTestId('duplicate-warning')).toBeInTheDocument();
    expect(screen.getByText(/Existing Video/)).toBeInTheDocument();
    expect(mockPush).not.toHaveBeenCalled();
  });

  it('"convert anyway" resubmits with force and navigates to the new job', async () => {
    (global.fetch as any)
      .mockResolvedValueOnce(
        jsonResponse(409, {
          existing_job: {
            job_id: 'job-existing',
            status: 'completed',
            created_at: '2026-08-01T00:00:00Z',
            video_title: 'Existing Video',
          },
        })
      )
      .mockResolvedValueOnce(jsonResponse(201, { job_id: 'job-new', status: 'pending' }));

    const user = userEvent.setup();
    await fillAndSubmit('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
    await screen.findByTestId('duplicate-warning');

    await user.click(screen.getByRole('button', { name: /convert anyway/i }));

    expect(mockPush).toHaveBeenCalledWith('/jobs/job-new');
    const secondCallBody = JSON.parse((global.fetch as any).mock.calls[1][1].body);
    expect(secondCallBody.force).toBe(true);
  });

  it('"view existing" navigates to the existing job without resubmitting', async () => {
    (global.fetch as any).mockResolvedValue(
      jsonResponse(409, {
        existing_job: {
          job_id: 'job-existing',
          status: 'completed',
          created_at: '2026-08-01T00:00:00Z',
          video_title: 'Existing Video',
        },
      })
    );

    const user = userEvent.setup();
    await fillAndSubmit('https://www.youtube.com/watch?v=dQw4w9WgXcQ');
    await screen.findByTestId('duplicate-warning');

    await user.click(screen.getByRole('button', { name: /view existing/i }));

    expect(mockPush).toHaveBeenCalledWith('/jobs/job-existing');
    expect(global.fetch).toHaveBeenCalledTimes(1);
  });

  describe('upload file mode', () => {
    const switchToUploadAndPickFile = async (
      user: ReturnType<typeof userEvent.setup>,
      filename = 'clip.mp4'
    ) => {
      render(<VideoSubmission />);
      await user.click(screen.getByRole('button', { name: /upload file/i }));
      const fileInput = screen.getByLabelText(/video or audio file/i) as HTMLInputElement;
      const file = new File(['fake-bytes'], filename, { type: 'video/mp4' });
      await user.upload(fileInput, file);
      return fileInput;
    };

    it('uploads the selected file to /jobs/upload and navigates to the job', async () => {
      (global.fetch as any).mockResolvedValue(
        jsonResponse(201, { job_id: 'job-upload-1', status: 'pending' })
      );

      const user = userEvent.setup();
      await switchToUploadAndPickFile(user);
      await user.click(screen.getByRole('button', { name: /convert to documentation/i }));

      expect(mockPush).toHaveBeenCalledWith('/jobs/job-upload-1');
      const [calledUrl, calledOptions] = (global.fetch as any).mock.calls[0];
      expect(calledUrl).toMatch(/\/jobs\/upload$/);
      expect(calledOptions.body).toBeInstanceOf(FormData);
      expect(calledOptions.headers).toBeUndefined();
    });

    it('disables submit until a file is chosen', async () => {
      render(<VideoSubmission />);
      const user = userEvent.setup();
      await user.click(screen.getByRole('button', { name: /upload file/i }));

      expect(screen.getByRole('button', { name: /convert to documentation/i })).toBeDisabled();
    });

    it('shows an error message when the upload fails', async () => {
      (global.fetch as any).mockResolvedValue(
        jsonResponse(422, { message: 'Unsupported file type' })
      );

      const user = userEvent.setup();
      await switchToUploadAndPickFile(user);
      await user.click(screen.getByRole('button', { name: /convert to documentation/i }));

      expect(await screen.findByText(/Unsupported file type/)).toBeInTheDocument();
      expect(mockPush).not.toHaveBeenCalled();
    });
  });
});
