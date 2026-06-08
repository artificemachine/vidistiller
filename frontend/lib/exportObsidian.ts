import JSZip from 'jszip';
import { buildSnapshotMap, toSnakeCase } from './utils';

interface SnapshotEntry {
  timestamp: number;
  image_url: string;
}

interface SlideEntry {
  slide_number: number;
  start_timestamp: number;
  end_timestamp: number;
  image_url?: string;
  ocr_text?: string;
  transcript_text?: string;
}

interface ExportOptions {
  title: string;
  videoUrl: string;
  transcriptText: string;
  snapshots: SnapshotEntry[];
  /** Base URL for resolving snapshot image paths (e.g. "http://localhost:8000") */
  baseUrl: string;
  slides?: SlideEntry[];
}

function formatTimestamp(seconds: number): string {
  const h = Math.floor(seconds / 3600).toString().padStart(2, '0');
  const m = Math.floor((seconds % 3600) / 60).toString().padStart(2, '0');
  const s = Math.floor(seconds % 60).toString().padStart(2, '0');
  return `${h}:${m}:${s}`;
}

function snapshotFilename(timestamp: number): string {
  return `snapshot_${timestamp.toFixed(2)}s.jpg`;
}

function buildMarkdown(
  title: string,
  videoUrl: string,
  lines: string[],
  snapMap: Map<number, SnapshotEntry[]>,
): string {
  const parts: string[] = [];
  parts.push(`# ${title}\n`);
  parts.push(`Source: ${videoUrl}\n`);

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];

    // Chapter header: ## [HH:MM:SS] Title
    const chapterMatch = line.match(/^## \[(\d{2}:\d{2}:\d{2})\]\s?(.+)/);
    if (chapterMatch) {
      parts.push(`\n## [${chapterMatch[1]}] ${chapterMatch[2].trim()}\n`);
      appendSnapshots(parts, snapMap.get(i));
      continue;
    }

    // Timestamped line: [HH:MM:SS] text
    const tsMatch = line.match(/^\[(\d{2}:\d{2}:\d{2})\]\s?(.*)/);
    if (tsMatch) {
      parts.push(`**[${tsMatch[1]}]** ${tsMatch[2]}\n`);
      appendSnapshots(parts, snapMap.get(i));
      continue;
    }

    // Plain non-empty line
    if (line.trim()) {
      parts.push(`${line}\n`);
      appendSnapshots(parts, snapMap.get(i));
    }
  }

  return parts.join('\n');
}

function appendSnapshots(parts: string[], snaps: SnapshotEntry[] | undefined): void {
  if (!snaps) return;
  for (const snap of snaps) {
    const fname = snapshotFilename(snap.timestamp);
    const alt = `Snapshot at ${formatTimestamp(snap.timestamp)}`;
    parts.push(`![${alt}](./images/${fname})\n`);
  }
}

async function fetchWithRetry(url: string, retries = 2): Promise<Response> {
  for (let i = 0; i <= retries; i++) {
    const res = await fetch(url);
    if (res.ok) return res;
    if (i < retries) await new Promise((r) => setTimeout(r, 300 * (i + 1)));
  }
  throw new Error(`Failed to fetch ${url}`);
}

async function fetchImages(
  snapshots: SnapshotEntry[],
  baseUrl: string,
): Promise<Map<string, Blob>> {
  const results = new Map<string, Blob>();
  const BATCH_SIZE = 5;
  for (let i = 0; i < snapshots.length; i += BATCH_SIZE) {
    const batch = snapshots.slice(i, i + BATCH_SIZE);
    const entries = await Promise.all(
      batch.map(async (snap) => {
        try {
          const url = `${baseUrl}${snap.image_url}`;
          const res = await fetchWithRetry(url);
          const blob = await res.blob();
          return { name: snapshotFilename(snap.timestamp), blob };
        } catch (err) {
          console.warn(`[export] failed to fetch snapshot at ${snap.timestamp}s:`, err);
          return null;
        }
      }),
    );
    for (const entry of entries) {
      if (entry) results.set(entry.name, entry.blob);
    }
  }
  return results;
}

function slideFilename(slideNumber: number): string {
  return `slide_${slideNumber.toString().padStart(3, '0')}.jpg`;
}

function buildSlidesSection(slides: SlideEntry[]): string {
  const parts: string[] = [];
  parts.push('\n## Detected Slides\n');

  for (const slide of slides) {
    const startTs = formatTimestamp(slide.start_timestamp);
    const endTs = formatTimestamp(slide.end_timestamp);
    const fname = slideFilename(slide.slide_number);

    parts.push(`### Slide ${slide.slide_number} (${startTs} – ${endTs})`);
    parts.push(`![Slide ${slide.slide_number}](./slides/${fname})\n`);

    if (slide.ocr_text?.trim()) {
      parts.push(`> **OCR Text:**`);
      for (const line of slide.ocr_text.trim().split('\n')) {
        parts.push(`> ${line}`);
      }
      parts.push('');
    }

    parts.push('---\n');
  }

  return parts.join('\n');
}

async function fetchSlideImages(
  slides: SlideEntry[],
  baseUrl: string,
): Promise<Map<string, Blob>> {
  const results = new Map<string, Blob>();
  const filtered = slides.filter((s) => s.image_url);
  const BATCH_SIZE = 5;
  for (let i = 0; i < filtered.length; i += BATCH_SIZE) {
    const batch = filtered.slice(i, i + BATCH_SIZE);
    const entries = await Promise.all(
      batch.map(async (slide) => {
        try {
          const url = `${baseUrl}${slide.image_url}`;
          const res = await fetchWithRetry(url);
          const blob = await res.blob();
          return { name: slideFilename(slide.slide_number), blob };
        } catch (err) {
          console.warn(`[export] failed to fetch slide ${slide.slide_number}:`, err);
          return null;
        }
      }),
    );
    for (const entry of entries) {
      if (entry) results.set(entry.name, entry.blob);
    }
  }
  return results;
}

interface SummaryExportOptions {
  title: string;
  summaryContent: string;
  baseUrl: string;
}

export async function exportSummaryToObsidian(options: SummaryExportOptions): Promise<void> {
  const { title, summaryContent, baseUrl } = options;
  const snakeName = toSnakeCase(title);

  // Extract all image references from the summary markdown
  const imageRefRe = /!\[([^\]]*)\]\(([^)]+)\)/g;
  const imageRefs: { alt: string; url: string; filename: string }[] = [];
  let match;
  while ((match = imageRefRe.exec(summaryContent)) !== null) {
    const url = match[2];
    if (url.startsWith('/static/')) {
      const filename = url.split('/').pop()!;
      imageRefs.push({ alt: match[1], url, filename });
    }
  }
  // Rewrite image URLs to relative ./images/ paths
  let markdown = summaryContent;
  for (const ref of imageRefs) {
    markdown = markdown.replace(
      new RegExp(`\\(${ref.url.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\)`, 'g'),
      `(./images/${ref.filename})`,
    );
  }

  // Fetch images referenced in summary — use same-origin proxy to avoid cross-origin fetch blocks
  const images = new Map<string, Blob>();
  const BATCH_SIZE = 5;
  for (let i = 0; i < imageRefs.length; i += BATCH_SIZE) {
    const batch = imageRefs.slice(i, i + BATCH_SIZE);
    const results = await Promise.all(
      batch.map(async (ref) => {
        try {
          const proxyUrl = `/snapproxy${ref.url}`;
          const res = await fetchWithRetry(proxyUrl);
          const blob = await res.blob();
          return { filename: ref.filename, blob };
        } catch (err) {
          console.warn(`[export] failed to fetch ${ref.url}:`, err);
          return null;
        }
      }),
    );
    for (const r of results) {
      if (r) images.set(r.filename, r.blob);
    }
  }
  const zip = new JSZip();
  const rootFolder = zip.folder(snakeName)!;
  rootFolder.file(`${snakeName}.md`, markdown);

  if (images.size > 0) {
    const imagesFolder = rootFolder.folder('images')!;
    for (const [name, blob] of images) {
      imagesFolder.file(name, blob);
    }
  }

  const blob = await zip.generateAsync({ type: 'blob' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${snakeName}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}

export async function exportToObsidian(options: ExportOptions): Promise<void> {
  const { title, videoUrl, transcriptText, snapshots, baseUrl, slides } = options;
  const lines = transcriptText.split('\n');
  const snapMap = buildSnapshotMap(lines, snapshots);

  let markdown = buildMarkdown(title, videoUrl, lines, snapMap);

  if (slides && slides.length > 0) {
    markdown += buildSlidesSection(slides);
  }

  const images = await fetchImages(snapshots, baseUrl);

  const snakeName = toSnakeCase(title);

  const zip = new JSZip();
  const rootFolder = zip.folder(snakeName)!;
  rootFolder.file(`${snakeName}.md`, markdown);

  if (images.size > 0) {
    const imagesFolder = rootFolder.folder('images')!;
    for (const [name, blob] of images) {
      imagesFolder.file(name, blob);
    }
  }

  if (slides && slides.length > 0) {
    const slideImages = await fetchSlideImages(slides, baseUrl);
    const slidesFolder = rootFolder.folder('slides')!;
    for (const [name, blob] of slideImages) {
      slidesFolder.file(name, blob);
    }
  }

  const blob = await zip.generateAsync({ type: 'blob' });

  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `${snakeName}.zip`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(a.href);
}
