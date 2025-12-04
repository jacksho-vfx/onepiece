import type { IpcMain } from 'electron';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { registerPeronaIpcHandlers } from '../perona';

const { startService, runCommand } = vi.hoisted(() => ({
  startService: vi.fn(),
  runCommand: vi.fn(),
}));

vi.mock('../pythonManager', () => ({
  startService,
  runCommand,
}));

describe('registerPeronaIpcHandlers', () => {
  let ipcMainMock: { handle: ReturnType<typeof vi.fn> };

  const getDashboardHandler = () => {
    const handler = ipcMainMock.handle.mock.calls.find((call) => call[0] === 'perona/web-dashboard')?.[1];

    if (!handler) {
      throw new Error('perona/web-dashboard handler was not registered');
    }

    return handler;
  };

  beforeEach(() => {
    ipcMainMock = { handle: vi.fn() };
    startService.mockReset();
    runCommand.mockReset();
    startService.mockResolvedValue({ id: 'service-id' });
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it('rejects invalid log levels with a helpful error', async () => {
    registerPeronaIpcHandlers(ipcMainMock as unknown as IpcMain);
    const handler = getDashboardHandler();

    await expect(handler({}, { logLevel: 'verbose' })).rejects.toThrow(
      "Invalid log level 'verbose'. Allowed values: debug, info, warning, error.",
    );
    expect(startService).not.toHaveBeenCalled();
  });

  it('allows valid log levels and passes the normalized value to the service', async () => {
    registerPeronaIpcHandlers(ipcMainMock as unknown as IpcMain);
    const handler = getDashboardHandler();

    await handler({}, { logLevel: 'DEBUG' });

    expect(startService).toHaveBeenCalledWith(
      'Perona web dashboard',
      expect.arrayContaining(['--log-level', 'debug']),
    );
  });
});
