import { afterEach, describe, expect, it, vi } from 'vitest';
import { runCommand } from '../pythonManager';
import * as pythonPathResolver from '../pythonPathResolver';

vi.mock('electron', () => ({
  Notification: vi.fn().mockImplementation(() => ({ show: vi.fn() })),
}));

describe('runCommand timeout handling', () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it('kills stalled processes and rejects with a timeout error', async () => {
    const timeoutMs = 200;
    vi.spyOn(pythonPathResolver, 'resolvePythonPath').mockResolvedValue(process.execPath);

    const longRunningScript = 'setInterval(() => {}, 1000);';

    await expect(
      runCommand(['-e', longRunningScript], { timeoutMs }),
    ).rejects.toThrow(`timed out after ${timeoutMs}ms`);
  });
});
