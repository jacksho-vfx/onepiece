import { describe, expect, it, vi } from 'vitest';
import type { BrowserWindow, IpcMain } from 'electron';
import { registerPythonIpcHandlers } from '../pythonManager';
import { spawn } from 'child_process';
import { resolvePythonPath } from '../pythonPathResolver';

vi.mock('child_process', () => {
  const { EventEmitter } = require('events');

  const spawnMock = vi.fn(() => {
    const stdout = new EventEmitter();
    const stderr = new EventEmitter();
    const process = new EventEmitter() as InstanceType<typeof EventEmitter> & {
      stdout: InstanceType<typeof EventEmitter>;
      stderr: InstanceType<typeof EventEmitter>;
      kill?: () => boolean;
    };

    process.stdout = stdout;
    process.stderr = stderr;
    process.kill = vi.fn().mockReturnValue(true);

    setImmediate(() => {
      process.emit('close', 0);
    });

    return process;
  });

  return { spawn: spawnMock };
});

vi.mock('electron', () => ({
  Notification: vi.fn().mockImplementation(() => ({ show: vi.fn() })),
}));

vi.mock('../pythonPathResolver', () => ({
  primePythonPath: vi.fn(),
  resolvePythonPath: vi.fn().mockResolvedValue('python'),
}));

const mockedResolvePythonPath = vi.mocked(resolvePythonPath);

describe('pythonManager animation cleanup handler', () => {
  it('forwards the validated scene name to the cleanup command', async () => {
    const handlers = new Map<string, (event: unknown, payload: unknown, ...args: unknown[]) => unknown>();
    const fakeIpcMain = {
      handle: (channel: string, listener: (event: unknown, payload: unknown, ...args: unknown[]) => unknown) => {
        handlers.set(channel, listener);
      },
    } as unknown as IpcMain;

    const fakeWindow = {
      webContents: {
        send: vi.fn(),
        isDestroyed: vi.fn().mockReturnValue(false),
      },
    } as unknown as BrowserWindow;

    mockedResolvePythonPath.mockResolvedValue('custom-python');

    registerPythonIpcHandlers(fakeIpcMain, fakeWindow, {} as never);

    const handler = handlers.get('onepiece/animation-cleanup');
    expect(handler).toBeDefined();

    await handler?.({}, { sceneName: '  DemoScene  ' });

    const spawnCalls = vi.mocked(spawn).mock.calls;
    expect(spawnCalls.length).toBeGreaterThan(0);

    const [pythonExecutable, args] = spawnCalls[0];
    expect(pythonExecutable).toBe('custom-python');
    const sceneFlagIndex = args.indexOf('--scene-name');

    expect(sceneFlagIndex).toBeGreaterThan(-1);
    expect(args[sceneFlagIndex + 1]).toBe('DemoScene');
  });
});
