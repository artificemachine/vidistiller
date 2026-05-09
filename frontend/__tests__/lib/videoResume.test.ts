import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  loadResume,
  saveResume,
  clearResume,
  pruneOldEntries,
  RESUME_KEY_PREFIX,
} from '@/lib/videoResume';

function createLocalStorageMock() {
  const store = new Map<string, string>();
  return {
    getItem: vi.fn((k: string) => store.get(k) ?? null),
    setItem: vi.fn((k: string, v: string) => store.set(k, v)),
    removeItem: vi.fn((k: string) => store.delete(k)),
    clear: vi.fn(() => store.clear()),
    get length() { return store.size; },
    key: vi.fn((i: number) => [...store.keys()][i] ?? null),
  };
}

describe('videoResume', () => {
  beforeEach(() => {
    vi.stubGlobal('localStorage', createLocalStorageMock());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe('saveResume / loadResume', () => {
    it('returns null when no entry exists', () => {
      expect(loadResume('abc123')).toBeNull();
    });

    it('persists and reads back the saved seconds', () => {
      saveResume('abc123', 42.5);
      expect(loadResume('abc123')).toBe(42.5);
    });

    it('keys entries by videoId', () => {
      saveResume('vid_a', 10);
      saveResume('vid_b', 20);
      expect(loadResume('vid_a')).toBe(10);
      expect(loadResume('vid_b')).toBe(20);
    });

    it('overwrites prior entries on the same key', () => {
      saveResume('abc123', 10);
      saveResume('abc123', 99);
      expect(loadResume('abc123')).toBe(99);
    });

    it('ignores invalid (non-finite) seconds', () => {
      saveResume('abc123', NaN);
      saveResume('abc123', Infinity);
      saveResume('abc123', -1);
      expect(loadResume('abc123')).toBeNull();
    });

    it('returns null on corrupted JSON', () => {
      localStorage.setItem(`${RESUME_KEY_PREFIX}corrupt`, 'not-json');
      expect(loadResume('corrupt')).toBeNull();
    });
  });

  describe('clearResume', () => {
    it('removes the entry for a videoId', () => {
      saveResume('abc123', 30);
      clearResume('abc123');
      expect(loadResume('abc123')).toBeNull();
    });
  });

  describe('pruneOldEntries', () => {
    it('removes entries older than maxAgeMs', () => {
      const now = Date.now();
      const oldKey = `${RESUME_KEY_PREFIX}stale`;
      const freshKey = `${RESUME_KEY_PREFIX}fresh`;
      localStorage.setItem(oldKey, JSON.stringify({ t: 5, savedAt: now - 100 * 24 * 3600 * 1000 }));
      localStorage.setItem(freshKey, JSON.stringify({ t: 5, savedAt: now - 1 * 24 * 3600 * 1000 }));

      pruneOldEntries(90 * 24 * 3600 * 1000);

      expect(localStorage.getItem(oldKey)).toBeNull();
      expect(localStorage.getItem(freshKey)).not.toBeNull();
    });

    it('does not touch keys outside the resume namespace', () => {
      localStorage.setItem('unrelated', 'keep-me');
      pruneOldEntries(0);
      expect(localStorage.getItem('unrelated')).toBe('keep-me');
    });

    it('drops entries with malformed payloads', () => {
      const badKey = `${RESUME_KEY_PREFIX}bad`;
      localStorage.setItem(badKey, 'not-json');
      pruneOldEntries(90 * 24 * 3600 * 1000);
      expect(localStorage.getItem(badKey)).toBeNull();
    });
  });
});
