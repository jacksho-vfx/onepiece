import path from 'path';
import { type IpcMain } from 'electron';
import { runCommand } from './pythonManager';
import { createTask } from './taskManager';

interface InspectPayload {
  scenePath: string;
}

interface RenderPayload {
  scenePath: string;
  format?: 'ppm' | 'png' | 'gif' | 'mp4';
  extraArgs?: string[];
}

export function registerChopperIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('chopper/inspect', async (_event, payload: InspectPayload) => {
    const scenePath = payload?.scenePath?.trim();

    if (!scenePath) {
      throw new Error('Scene path is required to inspect a scene.');
    }

    const args = ['-m', 'chopper', 'inspect', scenePath];

    return runCommand(args);
  });

  ipcMain.handle('chopper/render', async (_event, payload: RenderPayload) => {
    const scenePath = payload?.scenePath?.trim();

    if (!scenePath) {
      throw new Error('Scene path is required to render a scene.');
    }

    const args = ['-m', 'chopper', 'render', scenePath];

    if (payload?.format) {
      args.push('--format', payload.format);
    }

    if (payload?.extraArgs?.length) {
      args.push(...payload.extraArgs);
    }

    const label = `Chopper render: ${path.basename(scenePath) || scenePath}`;
    const taskId = await createTask(label, args);

    return { taskId, outputDir: path.dirname(scenePath) };
  });
}
