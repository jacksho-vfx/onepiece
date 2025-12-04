import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { BrowserWindow, IpcMain } from 'electron';

import { registerShotgridIpcHandlers } from '../shotgrid';

const { createTaskMock, runCommandMock } = vi.hoisted(() => ({
  createTaskMock: vi.fn(),
  runCommandMock: vi.fn(),
}));

vi.mock('../taskManager', () => ({
  createTask: createTaskMock,
}));

vi.mock('../pythonManager', () => ({
  runCommand: runCommandMock,
}));

vi.mock('electron', () => ({
  BrowserWindow: vi.fn(),
}));

type IpcHandler = (event: unknown, payload: any) => unknown;

const createIpcMainMock = (): { ipcMain: IpcMain; handlers: Map<string, IpcHandler> } => {
  const handlers = new Map<string, IpcHandler>();

  const ipcMain: IpcMain = {
    handle: (channel: string, handler: IpcHandler) => {
      handlers.set(channel, handler);
    },
  } as unknown as IpcMain;

  return { ipcMain, handlers };
};

describe('registerShotgridIpcHandlers validation', () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it('trims and validates package playlist payloads', async () => {
    createTaskMock.mockResolvedValue('task-1');
    const { ipcMain, handlers } = createIpcMainMock();

    registerShotgridIpcHandlers(ipcMain, {} as BrowserWindow);

    const handler = handlers.get('onepiece/shotgrid-package-playlist');

    expect(handler).toBeDefined();
    await handler?.({}, {
      project: '  demo ',
      playlist: ' playlist ',
      destination: ' dest ',
      recipient: ' recipient ',
    });

    expect(createTaskMock).toHaveBeenCalledWith(
      'Package playlist: playlist',
      [
        '-m',
        'onepiece',
        'shotgrid',
        'package-playlist',
        '--project',
        'demo',
        '--playlist',
        'playlist',
        '--destination',
        'dest',
        '--recipient',
        'recipient',
      ],
    );
  });

  it('rejects missing required package playlist fields', async () => {
    const { ipcMain, handlers } = createIpcMainMock();

    registerShotgridIpcHandlers(ipcMain, {} as BrowserWindow);

    const handler = handlers.get('onepiece/shotgrid-package-playlist');

    await expect(handler?.({}, { project: ' ', playlist: 'valid' })).rejects.toThrow('project is required');
    await expect(handler?.({}, { project: 'valid', playlist: '' })).rejects.toThrow('playlist is required');
    await expect(handler?.({}, { project: 'valid', playlist: 'valid', destination: '' })).rejects.toThrow(
      'destination cannot be empty',
    );
  });

  it('validates show setup payloads', async () => {
    const { ipcMain, handlers } = createIpcMainMock();

    registerShotgridIpcHandlers(ipcMain, {} as BrowserWindow);

    const handler = handlers.get('onepiece/shotgrid-show-setup');

    await expect(handler?.({}, { csvPath: '', project: 'proj' })).rejects.toThrow('csvPath is required');
    await expect(handler?.({}, { csvPath: 'path', project: ' ' })).rejects.toThrow('project is required');
  });

  it('passes trimmed show setup payloads to runCommand', async () => {
    runCommandMock.mockResolvedValue({ status: 'ok' });
    const { ipcMain, handlers } = createIpcMainMock();

    registerShotgridIpcHandlers(ipcMain, {} as BrowserWindow);

    const handler = handlers.get('onepiece/shotgrid-show-setup');

    await handler?.({}, { csvPath: ' /tmp/file.csv ', project: ' demo ', template: ' template ' });

    expect(runCommandMock).toHaveBeenCalledWith(['-m', 'onepiece', 'shotgrid', 'show-setup', '/tmp/file.csv', 'demo', '--template', 'template']);
  });

  it('normalizes episodes and rejects empty delivery payloads', async () => {
    createTaskMock.mockResolvedValue('task-2');
    const { ipcMain, handlers } = createIpcMainMock();

    registerShotgridIpcHandlers(ipcMain, {} as BrowserWindow);

    const handler = handlers.get('onepiece/shotgrid-deliver');

    await expect(
      handler?.({}, { project: 'proj', context: 'ctx', output: 'out', episodes: ['  '] }),
    ).rejects.toThrow('episodes cannot be empty');

    await handler?.({}, { project: ' proj ', context: ' ctx ', output: ' out ', episodes: [' ep1 ', 'ep2'], manifest: ' m ' });

    expect(createTaskMock).toHaveBeenCalledWith(
      'ShotGrid delivery: proj',
      [
        '-m',
        'onepiece',
        'shotgrid',
        'deliver',
        '--project',
        'proj',
        '--context',
        'ctx',
        '--output',
        'out',
        '--episodes',
        'ep1',
        'ep2',
        '--manifest',
        'm',
      ],
    );
  });
});
