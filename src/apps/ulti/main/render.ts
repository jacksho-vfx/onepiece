import { ipcMain } from 'electron';
import path from 'path';
import { createTask } from './taskManager';

type RenderSubmitPayload = {
  label?: string;
  dcc: string;
  scene: string;
  frames?: string;
  output: string;
  farm?: string;
  priority?: number;
  chunkSize?: number;
  user?: string;
  refreshCapabilities?: boolean;
  profileName?: string;
  optimize?: boolean;
  farmQueueDepth?: number;
  farmAverageFrameMs?: number;
};

function buildRenderSubmitArgs(payload: RenderSubmitPayload): string[] {
  const args = ['-m', 'onepiece', 'render', 'submit', '--dcc', payload.dcc, '--scene', payload.scene, '--output', payload.output];

  if (payload.frames?.trim()) {
    args.push('--frames', payload.frames.trim());
  }

  if (payload.farm?.trim()) {
    args.push('--farm', payload.farm.trim());
  }

  if (payload.priority !== undefined) {
    args.push('--priority', String(payload.priority));
  }

  if (payload.chunkSize !== undefined) {
    args.push('--chunk-size', String(payload.chunkSize));
  }

  if (payload.user?.trim()) {
    args.push('--user', payload.user.trim());
  }

  if (payload.refreshCapabilities) {
    args.push('--refresh-capabilities');
  }

  if (payload.profileName?.trim()) {
    args.push('--profile', payload.profileName.trim());
  }

  if (payload.optimize === false) {
    args.push('--no-optimize');
  }

  if (payload.farmQueueDepth !== undefined) {
    args.push('--farm-queue-depth', String(payload.farmQueueDepth));
  }

  if (payload.farmAverageFrameMs !== undefined) {
    args.push('--farm-average-frame-ms', String(payload.farmAverageFrameMs));
  }

  return args;
}

function buildRenderTaskLabel(payload: RenderSubmitPayload): string {
  const sceneName = path.basename(payload.scene || 'scene');
  const frames = payload.frames?.trim() || 'default frames';
  const farm = payload.farm?.trim() || 'farm';
  return payload.label ?? `Render submit (${sceneName} – ${frames} via ${farm})`;
}

export function registerRenderIpcHandlers(): void {
  ipcMain.handle('onepiece/render-submit', async (_event, payload: RenderSubmitPayload) => {
    if (!payload || !payload.dcc || !payload.scene || !payload.output) {
      throw new Error('Missing required render submission fields.');
    }

    const args = buildRenderSubmitArgs(payload);
    const label = buildRenderTaskLabel(payload);

    // This spawns the existing `onepiece render submit` CLI (apps.onepiece.render.submit.submit)
    // via the shared TaskManager so renders run as background tasks.
    return createTask(label, args);
  });
}

export { RenderSubmitPayload };
