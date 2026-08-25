import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

const globalStyles = readFileSync(
  resolve(process.cwd(), 'app/globals.css'),
  'utf8',
);

describe('global styles', () => {
  it('does not reset margin or padding after Tailwind utilities', () => {
    expect(globalStyles).not.toMatch(/\*\s*\{[^}]*\bmargin\s*:\s*0/);
    expect(globalStyles).not.toMatch(/\*\s*\{[^}]*\bpadding\s*:\s*0/);
  });
});
