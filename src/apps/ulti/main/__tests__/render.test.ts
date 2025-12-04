import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const { mockHandle, createTaskMock } = vi.hoisted(() => ({
  mockHandle: vi.fn(),
  createTaskMock: vi.fn(),
}));

vi.mock('electron', () => ({ ipcMain: { handle: mockHandle } }));
vi.mock('../taskManager', () => ({ createTask: createTaskMock }));

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
