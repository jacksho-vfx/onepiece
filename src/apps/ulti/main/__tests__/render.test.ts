import type { Stats } from 'fs';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { mockHandle, createTaskMock } = vi.hoisted(() => ({
  mockHandle: vi.fn(),
  createTaskMock: vi.fn(),
}));

const { statMock, mkdirMock, accessMock } = vi.hoisted(() => ({
  statMock: vi.fn(),
  mkdirMock: vi.fn(),
  accessMock: vi.fn(),
}));

vi.mock('electron', () => ({ ipcMain: { handle: mockHandle } }));
vi.mock('../taskManager', () => ({ createTask: createTaskMock }));
vi.mock('fs/promises', () => {
  const fsPromises = {
    stat: statMock,
    mkdir: mkdirMock,
    access: accessMock,
  };

  return { ...fsPromises, default: fsPromises };
});
vi.mock('fs', () => ({ constants: { W_OK: 2 } }));

import { registerRenderIpcHandlers } from '../render';

function getRenderSubmitHandler() {
  const renderHandlerCall = mockHandle.mock.calls.find(
    ([channel]) => channel === 'onepiece/render-submit'
  );

  return renderHandlerCall?.[1];
}

beforeEach(() => {
  mockHandle.mockReset();
  createTaskMock.mockReset();
  statMock.mockReset();
  mkdirMock.mockReset();
  accessMock.mockReset();

  statMock.mockResolvedValue({
    isFile: () => true,
    isDirectory: () => true,
  } as unknown as Stats);
  mkdirMock.mockResolvedValue(undefined);
  accessMock.mockResolvedValue(undefined);
});

afterEach(() => {
  vi.clearAllMocks();
});

describe('render submit priority validation', () => {
  it('passes through valid priority values', async () => {
    createTaskMock.mockResolvedValue('task-id');
    registerRenderIpcHandlers();

    const handler = getRenderSubmitHandler();
    expect(handler).toBeDefined();

    await handler?.({}, {
      scene: '/tmp/scene.blend',
      frames: '1-3',
      output: '/tmp/output',
      priority: 7,
    });

    expect(createTaskMock).toHaveBeenCalledTimes(1);
    const [, args] = createTaskMock.mock.calls[0];
    expect(args).toContain('--priority');
    expect(args).toContain('7');
  });

  it('rejects invalid priority values with a clear error', async () => {
    registerRenderIpcHandlers();

    const handler = getRenderSubmitHandler();
    expect(handler).toBeDefined();

    await expect(
      handler?.({}, {
        scene: '/tmp/scene.blend',
        frames: '10',
        output: '/tmp/output',
        priority: Number.NaN,
      })
    ).rejects.toThrow('Priority must be a finite number.');
    expect(createTaskMock).not.toHaveBeenCalled();
  });
});

describe('render submit path validation', () => {
  it('rejects missing scene paths with a descriptive error', async () => {
    statMock.mockRejectedValueOnce(Object.assign(new Error('not found'), { code: 'ENOENT' }));

    registerRenderIpcHandlers();

    const handler = getRenderSubmitHandler();
    expect(handler).toBeDefined();

    await expect(
      handler?.({}, {
        scene: '/missing/scene.blend',
        frames: '100-105',
        output: '/tmp/output',
      }),
    ).rejects.toThrow(
      'Scene file does not exist or is inaccessible: /missing/scene.blend',
    );

    expect(createTaskMock).not.toHaveBeenCalled();
  });

  it('rejects unwritable output directories before spawning a task', async () => {
    statMock.mockResolvedValueOnce({
      isFile: () => true,
      isDirectory: () => false,
    } as unknown as Stats);
    mkdirMock.mockRejectedValueOnce(new Error('permission denied'));

    registerRenderIpcHandlers();

    const handler = getRenderSubmitHandler();
    expect(handler).toBeDefined();

    await expect(
      handler?.({}, {
        scene: '/scenes/shot01.ma',
        frames: '1-10',
        output: '/restricted/output',
      }),
    ).rejects.toThrow(
      'Output directory is not writable or cannot be created: /restricted/output (permission denied)',
    );

    expect(createTaskMock).not.toHaveBeenCalled();
    expect(mkdirMock).toHaveBeenCalledWith('/restricted/output', { recursive: true });
  });
});
