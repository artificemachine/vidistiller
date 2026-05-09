export const RESUME_KEY_PREFIX = 'vidistiller:resume:';

interface ResumeEntry {
  t: number;
  savedAt: number;
}

function keyFor(videoId: string): string {
  return `${RESUME_KEY_PREFIX}${videoId}`;
}

function safeStorage(): Storage | null {
  try {
    return typeof window !== 'undefined' ? window.localStorage : null;
  } catch {
    return null;
  }
}

export function saveResume(videoId: string, seconds: number): void {
  if (!videoId || !Number.isFinite(seconds) || seconds < 0) return;
  const storage = safeStorage();
  if (!storage) return;
  const payload: ResumeEntry = { t: seconds, savedAt: Date.now() };
  try {
    storage.setItem(keyFor(videoId), JSON.stringify(payload));
  } catch {
    // quota exceeded or storage disabled — silently drop
  }
}

export function loadResume(videoId: string): number | null {
  if (!videoId) return null;
  const storage = safeStorage();
  if (!storage) return null;
  const raw = storage.getItem(keyFor(videoId));
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as ResumeEntry;
    if (typeof parsed?.t !== 'number' || !Number.isFinite(parsed.t)) return null;
    return parsed.t;
  } catch {
    return null;
  }
}

export function clearResume(videoId: string): void {
  const storage = safeStorage();
  if (!storage) return;
  storage.removeItem(keyFor(videoId));
}

export function pruneOldEntries(maxAgeMs: number): void {
  const storage = safeStorage();
  if (!storage) return;
  const cutoff = Date.now() - maxAgeMs;
  const toRemove: string[] = [];
  for (let i = 0; i < storage.length; i++) {
    const key = storage.key(i);
    if (!key || !key.startsWith(RESUME_KEY_PREFIX)) continue;
    const raw = storage.getItem(key);
    if (!raw) continue;
    try {
      const parsed = JSON.parse(raw) as ResumeEntry;
      if (typeof parsed?.savedAt !== 'number' || parsed.savedAt < cutoff) {
        toRemove.push(key);
      }
    } catch {
      toRemove.push(key);
    }
  }
  toRemove.forEach((k) => storage.removeItem(k));
}
