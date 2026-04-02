import { describe, it, expect } from 'vitest';
import { parseTimestamp, toSnakeCase } from '@/lib/utils';

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
