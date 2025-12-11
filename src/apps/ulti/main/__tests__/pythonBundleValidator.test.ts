import { promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { validatePythonBundle } from '../pythonBundleValidator';

async function createBundle(options: {
  baseDir: string;
  includeRuntime?: boolean;
  includeWheels?: boolean;
  includeDcc?: boolean;
  manifestContents?: string;
}): Promise<string> {
  const bundlePath = path.join(options.baseDir, `bundle-${Math.random().toString(16).slice(2)}`);
  await fs.mkdir(bundlePath, { recursive: true });

  await fs.writeFile(
    path.join(bundlePath, 'manifest.json'),
    options.manifestContents ??
      JSON.stringify({
        generatedAt: new Date().toISOString(),
        runtimeSource: '/artifacts/runtime',
        wheelsSource: '/artifacts/wheels',
        dccBridgeSource: '/artifacts/dcc',
      }),
  );

  if (options.includeRuntime !== false) {
    await fs.mkdir(path.join(bundlePath, 'runtime'), { recursive: true });
  }

  if (options.includeWheels !== false) {
    await fs.mkdir(path.join(bundlePath, 'wheels'), { recursive: true });
  }

  if (options.includeDcc !== false) {
    await fs.mkdir(path.join(bundlePath, 'dcc'), { recursive: true });
  }

  return bundlePath;
}

describe('validatePythonBundle', () => {
  let tempDir: string;

  beforeEach(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'python-bundle-validator-'));
  });

  afterEach(async () => {
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it('accepts bundles that contain a manifest and required directories', async () => {
    const bundlePath = await createBundle({ baseDir: tempDir });
    const result = await validatePythonBundle([bundlePath]);

    expect(result.status).toBe('valid');
    if (result.status === 'valid') {
      expect(result.attempt.bundlePath).toBe(bundlePath);
      expect(result.attempt.missing).toHaveLength(0);
      expect(result.attempt.manifest?.runtimeSource).toBe('/artifacts/runtime');
    }
  });

  it('reports missing payload directories', async () => {
    const bundlePath = await createBundle({ baseDir: tempDir, includeDcc: false, includeRuntime: false });
    const result = await validatePythonBundle([bundlePath]);

    expect(result.status).toBe('invalid');
    if (result.status === 'invalid') {
      expect(result.attempts[0].missing).toContain(path.join(bundlePath, 'runtime'));
      expect(result.attempts[0].missing).toContain(path.join(bundlePath, 'dcc'));
      expect(result.attempts[0].missing).not.toContain(path.join(bundlePath, 'wheels'));
    }
  });

  it('prefers the first valid bundle in the search paths', async () => {
    const emptyBundle = await createBundle({ baseDir: tempDir, includeWheels: false });
    const validBundle = await createBundle({ baseDir: tempDir });
    const result = await validatePythonBundle([emptyBundle, validBundle]);

    expect(result.status).toBe('valid');
    if (result.status === 'valid') {
      expect(result.attempt.bundlePath).toBe(validBundle);
    }
  });
});
