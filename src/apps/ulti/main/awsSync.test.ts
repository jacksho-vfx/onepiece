import fs from 'fs';
import os from 'os';
import path from 'path';
import { describe, it, expect, vi, afterEach, type Mock } from 'vitest';
import { registerAwsSyncIpcHandlers } from './awsSync';
import { createTask } from './taskManager';

vi.mock('./taskManager', () => ({
  createTask: vi.fn(),
}));

type MockIpcMain = {
  handle: ReturnType<typeof vi.fn>;
};

const setupHandler = (): ((event: unknown, payload: unknown) => Promise<unknown>) => {
  const ipcMain: MockIpcMain = { handle: vi.fn() };
  registerAwsSyncIpcHandlers(
    ipcMain as unknown as Parameters<typeof registerAwsSyncIpcHandlers>[0],
    {} as Parameters<typeof registerAwsSyncIpcHandlers>[1],
  );
  return ipcMain.handle.mock.calls[0][1];
};

afterEach(() => {
  vi.restoreAllMocks();
});

describe('registerAwsSyncIpcHandlers', () => {
  it('rejects when the local path does not exist', async () => {
    const handler = setupHandler();
    const resolvedMissingPath = path.resolve('missing/path');

    vi.spyOn(fs.promises, 'stat').mockRejectedValue(new Error('not found'));

    await expect(
      handler({}, { direction: 'upload', localPath: 'missing/path', remote: 's3://bucket/show/folder' }),
    ).rejects.toThrow(`Local path does not exist: ${resolvedMissingPath}`);

    expect(createTask).not.toHaveBeenCalled();
  });

  it('normalizes the local path and forwards it to the task runner', async () => {
    const handler = setupHandler();
    const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), 'aws-sync-'));
    const relativePath = path.relative(process.cwd(), tempDir);
    const taskId = 'task-123';

    const statSpy = vi.spyOn(fs.promises, 'stat');
    (createTask as unknown as Mock).mockResolvedValue(taskId);

    const result = await handler(
      {},
      { direction: 'download', localPath: relativePath, remote: 's3://bucket/show/folder' },
    );

    expect(result).toBe(taskId);
    expect(statSpy).toHaveBeenCalledWith(tempDir);
    expect(createTask).toHaveBeenCalledWith(
      'AWS sync from s3://bucket/show/folder',
      expect.arrayContaining([tempDir]),
    );

    fs.rmSync(tempDir, { recursive: true, force: true });
  });
});
