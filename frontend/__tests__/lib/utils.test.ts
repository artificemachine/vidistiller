import { describe, it, expect } from 'vitest';
import { parseTimestamp, toSnakeCase, errorMessage } from '@/lib/utils';

describe('errorMessage', () => {
  it('returns a plain string detail unchanged', () => {
    const err = { response: { data: { detail: 'endpoint not allowed' } } };
    expect(errorMessage(err, 'fallback')).toBe('endpoint not allowed');
  });

  it('flattens the FastAPI 422 array shape into a string', () => {
    const err = {
      response: {
        data: {
          detail: [
            { loc: ['body', 'llm_ollama_url'], msg: 'host not allowed', type: 'value_error' },
            { loc: ['body', 'llm_model'], msg: 'field required', type: 'missing' },
          ],
        },
      },
    };
    expect(errorMessage(err, 'fallback')).toBe('host not allowed; field required');
  });

  it('falls back when detail is absent, empty, or an unusable array', () => {
    expect(errorMessage({}, 'fallback')).toBe('fallback');
    expect(errorMessage({ response: { data: { detail: '' } } }, 'fallback')).toBe('fallback');
    expect(errorMessage({ response: { data: { detail: [{}] } } }, 'fallback')).toBe('fallback');
  });
});

describe('parseTimestamp', () => {
  it('parses [HH:MM:SS] format', () => {
    expect(parseTimestamp('[01:23:45]')).toBe(1 * 3600 + 23 * 60 + 45);
  });

  it('parses [MM:SS] format', () => {
    expect(parseTimestamp('[05:30]')).toBe(5 * 60 + 30);
  });

  it('parses [00:00:00] as zero', () => {
    expect(parseTimestamp('[00:00:00]')).toBe(0);
  });

  it('handles bare timestamps without brackets', () => {
    expect(parseTimestamp('01:30:00')).toBe(5400);
  });

  it('returns 0 for single-part input', () => {
    expect(parseTimestamp('42')).toBe(0);
  });
});

describe('toSnakeCase', () => {
  it('converts title to snake_case', () => {
    expect(toSnakeCase('OpenClaw Use Cases That Are Actually Insane'))
      .toBe('openclaw_use_cases_that_are_actually_insane');
  });

  it('strips special characters', () => {
    expect(toSnakeCase("What's New in React 19?!"))
      .toBe('whats_new_in_react_19');
  });

  it('collapses multiple spaces', () => {
    expect(toSnakeCase('Hello   World'))
      .toBe('hello_world');
  });

  it('returns "video" for empty string', () => {
    expect(toSnakeCase('')).toBe('video');
  });

  it('truncates at 80 characters', () => {
    const long = 'a '.repeat(50).trim();
    expect(toSnakeCase(long).length).toBeLessThanOrEqual(80);
  });
});
