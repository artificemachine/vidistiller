import { describe, it, expect } from 'vitest';
import { createRequire } from 'module';

const require = createRequire(import.meta.url);

// Default MAX_VIDEO_UPLOAD_SIZE_BYTES in backend/app/core/config.py.
const BACKEND_MAX_UPLOAD_BYTES = 4 * 1024 * 1024 * 1024;

describe('next.config', () => {
  it('lets the /api rewrite proxy carry uploads as large as the backend accepts', () => {
    // Regression: the rewrite proxy truncates request bodies at Next's 10 MB
    // default ("Request body exceeded 10MB for /api/jobs/upload"), so a
    // 300 MB upload from the home page reached the API cut short and failed
    // with a 400 after the socket hung up.
    const config = require('../../next.config.js');

    expect(config.experimental?.middlewareClientMaxBodySize).toBeGreaterThanOrEqual(
      BACKEND_MAX_UPLOAD_BYTES,
    );
  });
});
