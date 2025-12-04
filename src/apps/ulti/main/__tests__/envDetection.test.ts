import { promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import { afterAll, beforeAll, describe, expect, it } from 'vitest';

import { pathExists } from '../envDetection';

describe('pathExists', () => {
  let tempDir: string;

  beforeAll(async () => {
    tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'env-detection-'));
  });

  afterAll(async () => {
    await fs.rm(tempDir, { recursive: true, force: true });
  });

  it('returns false for missing paths', () => {
    expect(pathExists(path.join(tempDir, 'missing'))).toBe(false);
  });

  if (process.platform === 'win32') {
    it('considers existing files regardless of mode on Windows', async () => {
      const executable = path.join(tempDir, 'windows-file.exe');
      await fs.writeFile(executable, '');

      expect(pathExists(executable)).toBe(true);
    });
  } else {
    const matrix = [
      { name: 'executable file', mode: 0o755, expected: true },
      { name: 'non-executable file', mode: 0o644, expected: false },
    ];

    it.each(matrix)('respects execute permissions for %s', async ({ mode, expected }) => {
      const candidate = path.join(tempDir, `candidate-${mode.toString(8)}`);
      await fs.writeFile(candidate, 'echo', { mode });

      expect(pathExists(candidate)).toBe(expected);
    });
  }
});
