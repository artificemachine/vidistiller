import { describe, it, expect } from 'vitest';
import { createRequire } from 'module';
import { readFileSync } from 'fs';
import { resolve } from 'path';

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

  it('ships next.config.js in the runtime image so `next start` applies it', () => {
    // Regression: v1.18.2 raised the limit, but the runtime stage copied only
    // .next, node_modules, public and package.json. `next start` reads
    // next.config.js at startup, found none, and kept the 10 MB default.
    const dockerfile = readFileSync(resolve(__dirname, '../../Dockerfile'), 'utf-8');
    const runtimeStage = dockerfile.split(/^FROM .* AS runtime$/m)[1];

    expect(runtimeStage).toBeDefined();
    expect(runtimeStage).toMatch(/^COPY --from=builder \/app\/next\.config\.js \.\/next\.config\.js$/m);
  });
});
