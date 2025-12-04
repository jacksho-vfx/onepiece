import type { BrowserWindow, IpcMain } from 'electron';
import { createTask } from './taskManager';
import { runCommand } from './pythonManager';

type PackagePlaylistPayload = {
  project: string;
  playlist: string;
  destination?: string;
  recipient?: string;
};

type ShowSetupPayload = {
  csvPath: string;
  project: string;
  template?: string;
};

type DeliverPayload = {
  project: string;
  context: string;
  output: string;
  episodes?: string[];
  manifest?: string;
};

function buildPackagePlaylistArgs(payload: PackagePlaylistPayload): string[] {
  const args = [
    '-m',
    'onepiece',
    'shotgrid',
    'package-playlist',
    '--project',
    payload.project,
    '--playlist',
    payload.playlist,
  ];

  if (payload.destination) {
    args.push('--destination', payload.destination);
  }

  if (payload.recipient) {
    args.push('--recipient', payload.recipient);
  }

  return args;
}

function buildShowSetupArgs(payload: ShowSetupPayload): string[] {
  const args = ['-m', 'onepiece', 'shotgrid', 'show-setup', payload.csvPath, payload.project];

  if (payload.template) {
    args.push('--template', payload.template);
  }

  return args;
}

function buildDeliverArgs(payload: DeliverPayload): string[] {
  const args = [
    '-m',
    'onepiece',
    'shotgrid',
    'deliver',
    '--project',
    payload.project,
    '--context',
    payload.context,
    '--output',
    payload.output,
  ];

  if (payload.episodes?.length) {
    args.push('--episodes', ...payload.episodes);
  }

  if (payload.manifest) {
    args.push('--manifest', payload.manifest);
  }

  return args;
}

export function registerShotgridIpcHandlers(ipcMain: IpcMain, _browserWindow: BrowserWindow): void {
  ipcMain.handle('onepiece/shotgrid-package-playlist', async (_event, payload: PackagePlaylistPayload) => {
    const args = buildPackagePlaylistArgs(payload);
    const label = `Package playlist: ${payload.playlist}`;

    const taskId = await createTask(label, args);

    return { taskId };
  });

  ipcMain.handle('onepiece/shotgrid-show-setup', async (_event, payload: ShowSetupPayload) => {
    const args = buildShowSetupArgs(payload);
    return runCommand(args);
  });

  ipcMain.handle('onepiece/shotgrid-deliver', async (_event, payload: DeliverPayload) => {
    const args = buildDeliverArgs(payload);
    const label = `ShotGrid delivery: ${payload.project}`;

    const taskId = await createTask(label, args);

    return { taskId };
  });
}
