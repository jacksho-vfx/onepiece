import { ipcMain } from 'electron';
import path from 'path';
import { createTask } from './taskManager';
import { ensureSafeExternalUrl } from './url';

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
    if (typeof payload.priority !== 'number' || !Number.isFinite(payload.priority)) {
      throw new Error('Priority must be a finite number.');
    }

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

const DEFAULT_RENDER_DASHBOARD_BASE_URL = 'http://127.0.0.1:8080';

export function resolveRenderDashboardUrl(): string | null {
  const configuredBaseUrl =
    process.env.ONEPIECE_RENDER_DASHBOARD_BASE_URL?.trim() ||
    process.env.RENDER_DASHBOARD_BASE_URL?.trim() ||
    process.env.ONEPIECE_RENDER_DASHBOARD_URL?.trim() ||
    process.env.RENDER_DASHBOARD_URL?.trim() ||
    DEFAULT_RENDER_DASHBOARD_BASE_URL;

  if (!configuredBaseUrl) {
    return null;
  }

  try {
    const safeBase = ensureSafeExternalUrl(configuredBaseUrl);
    return new URL('/render', safeBase).toString();
  } catch (error) {
    console.warn('render.dashboard.url.invalid', error);
    return null;
  }
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

  ipcMain.handle('render/dashboard-url', async () => resolveRenderDashboardUrl());
}

export { RenderSubmitPayload };
