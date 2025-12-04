import { EventEmitter } from 'events';
import https from 'https';
import type { App, IpcMain } from 'electron';
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  UPDATE_CHECK_TIMEOUT_MS,
  UPDATE_CHECK_TIMEOUT_MESSAGE,
  checkForDesktopUpdate,
  registerUpdateIpcHandlers,
} from '../updateCheck';

class HangingRequest extends EventEmitter {
  timeoutId?: ReturnType<typeof setTimeout>;

  setTimeout(ms: number, callback: () => void): this {
    this.timeoutId = setTimeout(callback, ms);
    return this;
  }

  end(): void {}

  destroy(error?: Error): void {
    if (this.timeoutId) {
      clearTimeout(this.timeoutId);
    }

    this.emit('error', error ?? new Error('destroyed'));
    this.emit('close');
  }
}

describe('update check timeout handling', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('returns promptly when GitHub is unreachable', async () => {
    vi.spyOn(https, 'get').mockImplementation(() => {
      return new HangingRequest() as unknown as https.ClientRequest;
    });

    const updatePromise = checkForDesktopUpdate('1.0.0');

    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_TIMEOUT_MS);
    const result = await updatePromise;

    expect(result).toMatchObject({ hasUpdate: false, error: UPDATE_CHECK_TIMEOUT_MESSAGE });
  });

  it('surfaces a timeout error via IPC handler', async () => {
    const handle = vi.fn();
    const ipcMain = { handle } as unknown as IpcMain;
    const app = { getVersion: vi.fn(() => '1.2.3') } as unknown as App;

    vi.spyOn(https, 'get').mockImplementation(() => {
      return new HangingRequest() as unknown as https.ClientRequest;
    });

    registerUpdateIpcHandlers(ipcMain, app);

    const handler = handle.mock.calls[0][1];
    const responsePromise = handler();

    await vi.advanceTimersByTimeAsync(UPDATE_CHECK_TIMEOUT_MS);
    const response = await responsePromise;

    expect(response).toMatchObject({
      hasUpdate: false,
      error: UPDATE_CHECK_TIMEOUT_MESSAGE,
      currentVersion: '1.2.3',
    });
  });
});
