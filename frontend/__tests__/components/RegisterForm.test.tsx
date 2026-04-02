import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

const { mockGet, mockPost } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
}));

vi.mock('@/lib/api', () => ({
  default: { get: mockGet, post: mockPost },
  apiClient: { get: mockGet, post: mockPost },
}));

const mockPush = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: mockPush }),
}));

vi.mock('next/link', () => ({
  default: ({ children, href }: any) => <a href={href}>{children}</a>,
}));

import RegisterPage from '@/app/register/page';

function renderRegister() {
  return render(<RegisterPage />);
}

describe('RegisterPage error display', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('shows human-readable validation error messages from 422 response', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'password'], msg: 'String should have at least 8 characters', type: 'string_too_short' },
          ],
        },
      },
    });

    renderRegister();

    await user.type(screen.getByLabelText(/username/i), 'testuser');
    await user.type(screen.getByLabelText(/email/i), 'test@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'Aa1short');
    await user.type(screen.getByLabelText(/confirm password/i), 'Aa1short');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    expect(await screen.findByText(/at least 8 characters/i)).toBeInTheDocument();
  });

  it('does not display raw JSON in error output', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValueOnce({
      response: {
        status: 422,
        data: {
          detail: [
            { loc: ['body', 'password'], msg: 'Password must contain at least one uppercase letter', type: 'value_error' },
          ],
        },
      },
    });

    renderRegister();

    await user.type(screen.getByLabelText(/username/i), 'testuser');
    await user.type(screen.getByLabelText(/email/i), 'test@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'Aa1short');
    await user.type(screen.getByLabelText(/confirm password/i), 'Aa1short');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    await screen.findByText(/uppercase letter/i);

    // No raw JSON markers in the error display
    const errorDiv = screen.getByText(/uppercase letter/i).closest('div');
    expect(errorDiv?.textContent).not.toMatch(/\[\{/);
    expect(errorDiv?.textContent).not.toMatch(/"type":/);
  });

  it('shows client-side password mismatch error', async () => {
    const user = userEvent.setup();

    renderRegister();

    await user.type(screen.getByLabelText(/username/i), 'testuser');
    await user.type(screen.getByLabelText(/email/i), 'test@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'Password1');
    await user.type(screen.getByLabelText(/confirm password/i), 'Different1');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    expect(await screen.findByText(/passwords do not match/i)).toBeInTheDocument();
    // Should not call API on mismatch
    expect(mockPost).not.toHaveBeenCalled();
  });

  it('shows API error message for conflict (e.g. username taken)', async () => {
    const user = userEvent.setup();
    mockPost.mockRejectedValueOnce({
      response: {
        status: 409,
        data: { message: 'Username already taken' },
      },
    });

    renderRegister();

    await user.type(screen.getByLabelText(/username/i), 'taken');
    await user.type(screen.getByLabelText(/email/i), 'taken@example.com');
    await user.type(screen.getByLabelText(/^password$/i), 'GoodPass1');
    await user.type(screen.getByLabelText(/confirm password/i), 'GoodPass1');
    await user.click(screen.getByRole('button', { name: /create account/i }));

    expect(await screen.findByText(/username already taken/i)).toBeInTheDocument();
  });
});
