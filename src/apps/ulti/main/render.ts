import { ipcMain } from 'electron';
import path from 'path';
import { createTask } from './taskManager';

type RenderSubmitPayload = {
  profile?: string;
  scene: string;
  frames: string;
  output: string;
  user?: string;
  priority?: number;
  extraArgs?: string[];
  label?: string;
};

function buildRenderSubmitArgs(payload: RenderSubmitPayload): string[] {
  const args = ['-m', 'onepiece', 'render', 'submit'];

  if (payload.profile?.trim()) {
    args.push('--profile', payload.profile.trim());
  }

  args.push('--scene', payload.scene.trim());
  args.push('--frames', payload.frames.trim());
  args.push('--output', payload.output.trim());

  if (payload.user?.trim()) {
    args.push('--user', payload.user.trim());
  }

  if (payload.priority !== undefined) {
    args.push('--priority', String(payload.priority));
  }

  if (Array.isArray(payload.extraArgs) && payload.extraArgs.length > 0) {
    args.push(...payload.extraArgs);
  }

  return args;
}

function buildRenderTaskLabel(payload: RenderSubmitPayload): string {
  const sceneName = path.basename(payload.scene || 'scene');
  const frames = payload.frames?.trim() || 'frames';
  const profile = payload.profile?.trim();
  const profileSuffix = profile ? ` @ ${profile}` : '';
  return payload.label ?? `Render submit (${sceneName}${profileSuffix} – ${frames})`;
}

export function registerRenderIpcHandlers(): void {
  ipcMain.handle('onepiece/render-submit', async (_event, payload: RenderSubmitPayload) => {
    if (!payload || !payload.scene?.trim() || !payload.output?.trim() || !payload.frames?.trim()) {
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
