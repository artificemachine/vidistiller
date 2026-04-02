/**
 * Parse a [HH:MM:SS] or [MM:SS] timestamp string into total seconds.
 */
export function parseTimestamp(ts: string): number {
  const parts = ts.replace(/[\[\]]/g, '').split(':').map(Number);
  if (parts.length === 3) return parts[0] * 3600 + parts[1] * 60 + parts[2];
  if (parts.length === 2) return parts[0] * 60 + parts[1];
  return 0;
}

/**
 * Convert a title string to snake_case for filenames.
 * e.g. "OpenClaw Use Cases That Are Actually Insane" -> "openclaw_use_cases_that_are_actually_insane"
 */
export function toSnakeCase(title: string): string {
  return title
    .replace(/[^a-zA-Z0-9\s]/g, '')
    .trim()
    .replace(/\s+/g, '_')
    .toLowerCase()
    .slice(0, 80) || 'video';
}

/**
 * Build a map: lineIndex -> snapshots to render after that line.
 * Works with any object that has a `timestamp` number field.
 */
export function buildSnapshotMap<T extends { timestamp: number }>(
  lines: string[],
  snapshots: T[],
): Map<number, T[]> {
  if (snapshots.length === 0) return new Map<number, T[]>();

  const lineTimestamps: { index: number; seconds: number }[] = [];
  lines.forEach((line, i) => {
    const m = line.match(/^(?:## )?\[(\d{2}):(\d{2}):(\d{2})\]/);
    if (m) {
      lineTimestamps.push({ index: i, seconds: +m[1] * 3600 + +m[2] * 60 + +m[3] });
    }
  });
  if (lineTimestamps.length === 0) return new Map<number, T[]>();

  const map = new Map<number, T[]>();
  for (const snap of [...snapshots].sort((a, b) => a.timestamp - b.timestamp)) {
    let bestIdx = lineTimestamps[0].index;
    for (const lt of lineTimestamps) {
      if (lt.seconds <= snap.timestamp) bestIdx = lt.index;
      else break;
    }
    const arr = map.get(bestIdx) || [];
    arr.push(snap);
    map.set(bestIdx, arr);
  }
  return map;
}
