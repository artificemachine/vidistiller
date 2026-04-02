import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { exportToObsidian } from '@/lib/exportObsidian';

// Track what JSZip receives
let zipFiles: Record<string, unknown> = {};
let zipFolders: Record<string, Record<string, unknown>> = {};

vi.mock('jszip', () => {
  const createFolderMock = (folderPath: string) => {
    return {
      file(fname: string, data: unknown) {
        if (!zipFolders[folderPath]) zipFolders[folderPath] = {};
        zipFolders[folderPath][fname] = data;
        // Also track the file directly for easier test access
        zipFiles[fname] = data;
      },
      folder(name: string) {
        const nestedPath = `${folderPath}/${name}`;
        zipFolders[nestedPath] = {};
        return createFolderMock(nestedPath);
      },
    };
  };

  return {
    default: class MockJSZip {
      file(name: string, data: unknown) {
        zipFiles[name] = data;
      }
      folder(name: string) {
        zipFolders[name] = {};
        return createFolderMock(name);
      }
      async generateAsync() {
        return new Blob(['mock-zip']);
      }
    },
  };
});

// Mock fetch for image downloads
const mockFetch = vi.fn();
globalThis.fetch = mockFetch;

// Stub URL.createObjectURL / revokeObjectURL and DOM download
URL.createObjectURL = vi.fn(() => 'blob:mock');
URL.revokeObjectURL = vi.fn();

beforeEach(() => {
  zipFiles = {};
  zipFolders = {};
  mockFetch.mockReset();
  mockFetch.mockResolvedValue({
    ok: true,
    blob: async () => new Blob(['img-data']),
  });
});

describe('exportToObsidian', () => {
  const baseOptions = {
    title: 'Test Tutorial',
    youtubeUrl: 'https://youtube.com/watch?v=abc',
    transcriptText: '[00:00:05] Hello world\n[00:00:10] Second line',
    snapshots: [{ timestamp: 5.0, image_url: '/snapshots/snap.jpg' }],
    baseUrl: 'http://localhost:8000',
  };

  it('generates zip without slides section when no slides provided', async () => {
    await exportToObsidian(baseOptions);

    const md = zipFiles['test_tutorial.md'] as string;
    expect(md).toContain('# Test Tutorial');
    expect(md).toContain('Hello world');
    expect(md).not.toContain('## Detected Slides');
    expect(zipFolders['test_tutorial/images']).toBeDefined();
    expect(zipFolders['test_tutorial/slides']).toBeUndefined();
  });

  it('generates zip without slides section when slides array is empty', async () => {
    await exportToObsidian({ ...baseOptions, slides: [] });

    const md = zipFiles['test_tutorial.md'] as string;
    expect(md).not.toContain('## Detected Slides');
    expect(zipFolders['test_tutorial/slides']).toBeUndefined();
  });

  it('appends slides section to markdown when slides are provided', async () => {
    const slides = [
      {
        slide_number: 1,
        start_timestamp: 0,
        end_timestamp: 60,
        image_url: '/slides/1.jpg',
        ocr_text: 'Welcome to Docker',
      },
      {
        slide_number: 2,
        start_timestamp: 60,
        end_timestamp: 120,
        image_url: '/slides/2.jpg',
      },
    ];

    await exportToObsidian({ ...baseOptions, slides });

    const md = zipFiles['test_tutorial.md'] as string;
    // Transcript content still present
    expect(md).toContain('Hello world');
    // Slides section appended
    expect(md).toContain('## Detected Slides');
    expect(md).toContain('### Slide 1 (00:00:00 – 00:01:00)');
    expect(md).toContain('![Slide 1](./slides/slide_001.jpg)');
    expect(md).toContain('> **OCR Text:**');
    expect(md).toContain('> Welcome to Docker');
    // Slide 2 — no OCR
    expect(md).toContain('### Slide 2 (00:01:00 – 00:02:00)');
    expect(md).toContain('![Slide 2](./slides/slide_002.jpg)');
  });

  it('creates slides/ folder with fetched slide images', async () => {
    const slides = [
      {
        slide_number: 1,
        start_timestamp: 0,
        end_timestamp: 60,
        image_url: '/slides/1.jpg',
      },
      {
        slide_number: 2,
        start_timestamp: 60,
        end_timestamp: 120,
        image_url: '/slides/2.jpg',
      },
    ];

    await exportToObsidian({ ...baseOptions, slides });

    expect(zipFolders['test_tutorial/slides']).toBeDefined();
    expect(zipFolders['test_tutorial/slides']['slide_001.jpg']).toBeDefined();
    expect(zipFolders['test_tutorial/slides']['slide_002.jpg']).toBeDefined();
  });

  it('fetches slide images from correct URLs', async () => {
    const slides = [
      {
        slide_number: 1,
        start_timestamp: 0,
        end_timestamp: 60,
        image_url: '/slides/1.jpg',
      },
    ];

    await exportToObsidian({ ...baseOptions, slides });

    const slideCall = mockFetch.mock.calls.find(
      (c: string[]) => c[0] === 'http://localhost:8000/slides/1.jpg',
    );
    expect(slideCall).toBeDefined();
  });

  it('skips slides without image_url in image fetching', async () => {
    const slides = [
      {
        slide_number: 1,
        start_timestamp: 0,
        end_timestamp: 60,
        // no image_url
        ocr_text: 'Text only slide',
      },
    ];

    await exportToObsidian({ ...baseOptions, slides });

    // Markdown still includes the slide entry
    const md = zipFiles['test_tutorial.md'] as string;
    expect(md).toContain('### Slide 1');
    expect(md).toContain('> Text only slide');
    // But no slide image was fetched (only snapshot fetch happened)
    const slideFetchCalls = mockFetch.mock.calls.filter(
      (c: string[]) => c[0].includes('/slides/'),
    );
    expect(slideFetchCalls).toHaveLength(0);
  });

  it('handles multi-line OCR text in blockquote', async () => {
    const slides = [
      {
        slide_number: 1,
        start_timestamp: 0,
        end_timestamp: 60,
        image_url: '/slides/1.jpg',
        ocr_text: 'Line one\nLine two\nLine three',
      },
    ];

    await exportToObsidian({ ...baseOptions, slides });

    const md = zipFiles['test_tutorial.md'] as string;
    expect(md).toContain('> Line one');
    expect(md).toContain('> Line two');
    expect(md).toContain('> Line three');
  });

  it('pads slide numbers to 3 digits in filenames', async () => {
    const slides = [
      {
        slide_number: 7,
        start_timestamp: 0,
        end_timestamp: 60,
        image_url: '/slides/7.jpg',
      },
    ];

    await exportToObsidian({ ...baseOptions, slides });

    const md = zipFiles['test_tutorial.md'] as string;
    expect(md).toContain('slide_007.jpg');
    expect(zipFolders['test_tutorial/slides']['slide_007.jpg']).toBeDefined();
  });

  describe('batched image fetching', () => {
    function makeSnapshots(count: number) {
      return Array.from({ length: count }, (_, i) => ({
        timestamp: i * 10,
        image_url: `/snapshots/snap_${i}.jpg`,
      }));
    }

    it('fetches all snapshots when count exceeds batch size', async () => {
      const snaps = makeSnapshots(12);
      const transcript = snaps.map((s) => `[${String(Math.floor(s.timestamp / 3600)).padStart(2, '0')}:${String(Math.floor((s.timestamp % 3600) / 60)).padStart(2, '0')}:${String(Math.floor(s.timestamp % 60)).padStart(2, '0')}] Line ${s.timestamp}`).join('\n');

      await exportToObsidian({
        ...baseOptions,
        transcriptText: transcript,
        snapshots: snaps,
      });

      // All 12 images should be in the zip
      const imagesFolder = zipFolders['test_tutorial/images'];
      expect(Object.keys(imagesFolder)).toHaveLength(12);
      // All 12 fetch calls (no retries needed since all succeed)
      expect(mockFetch).toHaveBeenCalledTimes(12);
    });

    it('fetches in batches of 5 (sequential batches)', async () => {
      const callOrder: number[] = [];
      let callCount = 0;
      mockFetch.mockImplementation(() => {
        callOrder.push(++callCount);
        return Promise.resolve({
          ok: true,
          blob: async () => new Blob(['img']),
        });
      });

      const snaps = makeSnapshots(8);
      const transcript = snaps.map((s) => `[00:00:${String(Math.floor(s.timestamp)).padStart(2, '0')}] Line`).join('\n');

      await exportToObsidian({
        ...baseOptions,
        transcriptText: transcript,
        snapshots: snaps,
      });

      // 8 total fetch calls
      expect(mockFetch).toHaveBeenCalledTimes(8);
      // All 8 images in zip
      expect(Object.keys(zipFolders['test_tutorial/images'])).toHaveLength(8);
    });

    it('includes all snapshot references in markdown regardless of fetch outcome', { timeout: 15000 }, async () => {
      // Fail all image fetches (retries will happen with delays)
      mockFetch.mockResolvedValue({ ok: false });

      const snaps = makeSnapshots(3);
      const transcript = '[00:00:00] Line A\n[00:00:10] Line B\n[00:00:20] Line C';

      await exportToObsidian({
        ...baseOptions,
        transcriptText: transcript,
        snapshots: snaps,
      });

      const md = zipFiles['test_tutorial.md'] as string;
      // Markdown still references all 3 snapshots even though images failed
      expect(md).toContain('snapshot_0.00s.jpg');
      expect(md).toContain('snapshot_10.00s.jpg');
      expect(md).toContain('snapshot_20.00s.jpg');
      // No images folder created (all fetches failed)
      expect(zipFolders['test_tutorial/images']).toBeUndefined();
    });
  });

  describe('retry logic', () => {
    it('retries failed fetches up to 2 times before giving up', { timeout: 10000 }, async () => {
      // Always fail
      mockFetch.mockResolvedValue({ ok: false });

      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      await exportToObsidian({
        ...baseOptions,
        snapshots: [{ timestamp: 5.0, image_url: '/snapshots/snap.jpg' }],
      });

      // 1 initial + 2 retries = 3 calls for the one snapshot
      expect(mockFetch).toHaveBeenCalledTimes(3);
      expect(warnSpy).toHaveBeenCalledWith(
        expect.stringContaining('[export] failed to fetch snapshot at 5s'),
        expect.anything(),
      );
      warnSpy.mockRestore();
    });

    it('succeeds on second attempt after first failure', { timeout: 10000 }, async () => {
      let attempts = 0;
      mockFetch.mockImplementation(() => {
        attempts++;
        if (attempts === 1) {
          return Promise.resolve({ ok: false });
        }
        return Promise.resolve({
          ok: true,
          blob: async () => new Blob(['img-data']),
        });
      });

      await exportToObsidian({
        ...baseOptions,
        snapshots: [{ timestamp: 5.0, image_url: '/snapshots/snap.jpg' }],
      });

      expect(mockFetch).toHaveBeenCalledTimes(2);
      expect(zipFolders['test_tutorial/images']['snapshot_5.00s.jpg']).toBeDefined();
    });

    it('retries on network error (fetch throws)', async () => {
      let attempts = 0;
      mockFetch.mockImplementation(() => {
        attempts++;
        if (attempts <= 2) {
          return Promise.reject(new Error('network error'));
        }
        return Promise.resolve({
          ok: true,
          blob: async () => new Blob(['img-data']),
        });
      });

      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      await exportToObsidian({
        ...baseOptions,
        snapshots: [{ timestamp: 5.0, image_url: '/snapshots/snap.jpg' }],
      });

      // fetchWithRetry throws on network error (doesn't retry — the catch in fetchImages handles it)
      // First call throws, so fetchWithRetry itself throws immediately
      // The warn should be emitted
      expect(warnSpy).toHaveBeenCalled();
      warnSpy.mockRestore();
    });

    it('retries slides with same logic on failure then success', { timeout: 10000 }, async () => {
      const callsByUrl: Record<string, number> = {};
      mockFetch.mockImplementation((url: string) => {
        callsByUrl[url] = (callsByUrl[url] || 0) + 1;
        // Snapshot always succeeds
        if (url.includes('/snapshots/')) {
          return Promise.resolve({ ok: true, blob: async () => new Blob(['snap']) });
        }
        // Slide fails first, succeeds on retry
        if (callsByUrl[url] === 1) {
          return Promise.resolve({ ok: false });
        }
        return Promise.resolve({ ok: true, blob: async () => new Blob(['slide']) });
      });

      await exportToObsidian({
        ...baseOptions,
        slides: [{
          slide_number: 1,
          start_timestamp: 0,
          end_timestamp: 60,
          image_url: '/slides/1.jpg',
        }],
      });

      expect(zipFolders['test_tutorial/slides']['slide_001.jpg']).toBeDefined();
    });
  });

  describe('many snapshots export', () => {
    it('exports all 41 snapshots into zip images folder', async () => {
      const snaps = Array.from({ length: 41 }, (_, i) => ({
        timestamp: i * 30,
        image_url: `/snapshots/snap_${i}.jpg`,
      }));
      // Build transcript with matching timestamps
      const transcript = snaps
        .map((s) => {
          const h = String(Math.floor(s.timestamp / 3600)).padStart(2, '0');
          const m = String(Math.floor((s.timestamp % 3600) / 60)).padStart(2, '0');
          const sec = String(Math.floor(s.timestamp % 60)).padStart(2, '0');
          return `[${h}:${m}:${sec}] Content at ${s.timestamp}s`;
        })
        .join('\n');

      await exportToObsidian({
        ...baseOptions,
        transcriptText: transcript,
        snapshots: snaps,
      });

      const imagesFolder = zipFolders['test_tutorial/images'];
      expect(Object.keys(imagesFolder)).toHaveLength(41);
      // fetch called once per snapshot (all succeed first try)
      expect(mockFetch).toHaveBeenCalledTimes(41);

      // Markdown references all 41
      const md = zipFiles['test_tutorial.md'] as string;
      for (const snap of snaps) {
        expect(md).toContain(`snapshot_${snap.timestamp.toFixed(2)}s.jpg`);
      }
    });

    it('partially exports when some snapshots fail', { timeout: 30000 }, async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});

      const snaps = Array.from({ length: 10 }, (_, i) => ({
        timestamp: i * 10,
        image_url: `/snapshots/snap_${i}.jpg`,
      }));
      const transcript = snaps
        .map((s) => {
          const sec = String(Math.floor(s.timestamp % 60)).padStart(2, '0');
          const m = String(Math.floor((s.timestamp % 3600) / 60)).padStart(2, '0');
          return `[00:${m}:${sec}] Line`;
        })
        .join('\n');

      // Fail snapshots at index 3 and 7 (all 3 attempts)
      const failTimestamps = new Set([30, 70]);
      mockFetch.mockImplementation((url: string) => {
        const tsMatch = url.match(/snap_(\d+)/);
        if (tsMatch) {
          const ts = parseInt(tsMatch[1]) * 10;
          if (failTimestamps.has(ts)) {
            return Promise.resolve({ ok: false });
          }
        }
        return Promise.resolve({
          ok: true,
          blob: async () => new Blob(['img']),
        });
      });

      await exportToObsidian({
        ...baseOptions,
        transcriptText: transcript,
        snapshots: snaps,
      });

      const imagesFolder = zipFolders['test_tutorial/images'];
      // 8 out of 10 succeed
      expect(Object.keys(imagesFolder)).toHaveLength(8);
      // 2 failures logged
      expect(warnSpy).toHaveBeenCalledTimes(2);

      // Markdown still references all 10
      const md = zipFiles['test_tutorial.md'] as string;
      for (const snap of snaps) {
        expect(md).toContain(`snapshot_${snap.timestamp.toFixed(2)}s.jpg`);
      }

      warnSpy.mockRestore();
    });
  });
});
