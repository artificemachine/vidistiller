import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

type Version = [number, number, number];

const manifest = JSON.parse(
  readFileSync(resolve(__dirname, '../../package.json'), 'utf8'),
);
const lockfile = JSON.parse(
  readFileSync(resolve(__dirname, '../../package-lock.json'), 'utf8'),
);

function parseVersion(version: string): Version {
  const match = /(?:^|[^\d])(\d+)\.(\d+)\.(\d+)/.exec(version);
  expect(match, `expected a numeric version in ${version}`).not.toBeNull();
  return [Number(match![1]), Number(match![2]), Number(match![3])];
}

function versionAtLeast(actual: Version, minimum: Version): boolean {
  for (let index = 0; index < actual.length; index += 1) {
    if (actual[index] !== minimum[index]) {
      return actual[index] > minimum[index];
    }
  }
  return true;
}

describe('security-sensitive frontend dependencies', () => {
  it.each([
    ['next', '15.5.28', 15],
    ['@sentry/nextjs', '10.75.2', 10],
  ])('%s stays on its supported major at the patched minimum', (name, minimum, major) => {
    const manifestRange = manifest.dependencies[name];
    const lockRange = lockfile.packages[''].dependencies[name];
    const resolvedVersion = lockfile.packages[`node_modules/${name}`].version;
    const minimumVersion = parseVersion(minimum);
    const manifestMinimum = parseVersion(manifestRange);
    const lockMinimum = parseVersion(lockRange);
    const resolved = parseVersion(resolvedVersion);

    expect(manifestRange).not.toContain('||');
    expect(lockRange).toBe(manifestRange);
    expect(manifestMinimum[0]).toBe(major);
    expect(lockMinimum[0]).toBe(major);
    expect(resolved[0]).toBe(major);
    expect(versionAtLeast(manifestMinimum, minimumVersion)).toBe(true);
    expect(versionAtLeast(lockMinimum, minimumVersion)).toBe(true);
    expect(versionAtLeast(resolved, minimumVersion)).toBe(true);
  });
});
