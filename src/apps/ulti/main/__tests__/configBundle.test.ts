import { EventEmitter } from 'events';
import { spawnSync } from 'child_process';
import { createWriteStream, promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import yazl from 'yazl';
import type { App } from 'electron';

import { createConfigBundle, extractConfigBundleArchive } from '../configBundle';

const spawnMock = vi.fn<typeof import('child_process').spawn>();

vi.mock('child_process', async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process');

  return {
    ...actual,
    spawn: (...args) => spawnMock(...args),
  };
});

vi.mock('electron', () => ({
  dialog: {},
  BrowserWindow: class {},
  ipcMain: {},
  app: { getPath: vi.fn() },
}));

vi.mock('../configManager', () => ({
  ensureDefaultConfig: vi.fn().mockResolvedValue({
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
    enableNotifications: true,
  }),
  getConfigPath: vi.fn().mockReturnValue(path.join(os.tmpdir(), 'config-bundle-test', 'config.json')),
  saveConfig: vi.fn(),
}));

beforeEach(async () => {
  const actual = await vi.importActual<typeof import('child_process')>('child_process');
  spawnMock.mockImplementation(actual.spawn);
  spawnMock.mockClear();
});

async function createZipArchive(
  zipPath: string,
  entries: { name: string; data: string | Buffer; mode?: number }[],
): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    const zipfile = new yazl.ZipFile();

    for (const entry of entries) {
      zipfile.addBuffer(Buffer.isBuffer(entry.data) ? entry.data : Buffer.from(entry.data), entry.name, {
        mode: entry.mode,
      });
    }

    zipfile.end();

    zipfile.outputStream.pipe(createWriteStream(zipPath)).on('close', resolve).on('error', reject);
  });
}

async function pathExists(targetPath: string): Promise<boolean> {
  try {
    await fs.access(targetPath);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return false;
    }
    throw error;
  }
}

describe('extractConfigBundleArchive', () => {
  it('rejects archives that attempt path traversal or include symlinks', async () => {
    const stagingDir = await fs.mkdtemp(path.join(os.tmpdir(), 'config-bundle-test-'));
    const zipSourceDir = await fs.mkdtemp(path.join(os.tmpdir(), 'config-bundle-zip-'));
    const payloadDir = path.join(zipSourceDir, 'payload');
    const zipPath = path.join(zipSourceDir, 'malicious.zip');
    const outsideFile = path.resolve(stagingDir, '..', 'outside.txt');

    try {
      await fs.mkdir(payloadDir, { recursive: true });

      const traversalTarget = path.join(zipSourceDir, 'traversal.txt');
      await fs.writeFile(traversalTarget, 'evil');

      const symlinkPath = path.join(payloadDir, 'link-to-nowhere');
      await fs.symlink('/tmp/nowhere', symlinkPath);

      spawnSync('zip', ['-y', zipPath, '../traversal.txt', 'link-to-nowhere'], { cwd: payloadDir });

      await expect(extractConfigBundleArchive(zipPath, stagingDir)).rejects.toThrow();

      expect(await pathExists(outsideFile)).toBe(false);
      expect(await pathExists(path.join(stagingDir, 'link-to-nowhere'))).toBe(false);
    } finally {
      await fs.rm(stagingDir, { recursive: true, force: true });
      await fs.rm(zipSourceDir, { recursive: true, force: true });
    }
  });

  it('extracts regular files into the staging directory', async () => {
    const stagingDir = await fs.mkdtemp(path.join(os.tmpdir(), 'config-bundle-test-'));
    const zipPath = path.join(stagingDir, 'valid.zip');
    const extractedFile = path.join(stagingDir, 'nested', 'file.txt');

    try {
      await createZipArchive(zipPath, [{ name: 'nested/file.txt', data: 'hello world' }]);

      await extractConfigBundleArchive(zipPath, stagingDir);

      const contents = await fs.readFile(extractedFile, 'utf-8');
      expect(contents).toBe('hello world');
    } finally {
      await fs.rm(stagingDir, { recursive: true, force: true });
    }
  });
});

describe('createConfigBundle', () => {
  it('throws a clear error when the zip binary is missing', async () => {
    const app = { getPath: vi.fn().mockReturnValue(os.tmpdir()) } as unknown as App;

    spawnMock.mockImplementation(() => {
      const fakeChild = new EventEmitter();
      // @ts-expect-error - stderr is optional for the mock child process
      fakeChild.stderr = new EventEmitter();

      queueMicrotask(() => {
        const error = new Error('spawn ENOENT');
        (error as NodeJS.ErrnoException).code = 'ENOENT';
        fakeChild.emit('error', error);
      });

      // @ts-expect-error - the mock child process only needs to support events
      return fakeChild;
    });

    await expect(createConfigBundle(app)).rejects.toThrow(/`zip` command is missing/i);

    const actual = await vi.importActual<typeof import('child_process')>('child_process');
    spawnMock.mockImplementation(actual.spawn);
  });
});
