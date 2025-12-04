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

function trimRequired(value: string | undefined, field: string): string {
  const trimmed = value?.trim() ?? '';

  if (!trimmed) {
    throw new Error(`${field} is required`);
  }

  return trimmed;
}

function trimOptional(value: string | undefined, field: string): string | undefined {
  if (value === undefined) {
    return undefined;
  }

  const trimmed = value.trim();

  if (!trimmed) {
    throw new Error(`${field} cannot be empty`);
  }

  return trimmed;
}

function normalizeEpisodes(episodes?: string[]): string[] | undefined {
  if (!episodes) {
    return undefined;
  }

  const normalized = episodes.map((episode) => episode.trim()).filter((episode) => episode.length > 0);

  if (!normalized.length) {
    throw new Error('episodes cannot be empty');
  }

  return normalized;
}

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
    const sanitizedPayload: PackagePlaylistPayload = {
      project: trimRequired(payload.project, 'project'),
      playlist: trimRequired(payload.playlist, 'playlist'),
      destination: trimOptional(payload.destination, 'destination'),
      recipient: trimOptional(payload.recipient, 'recipient'),
    };

    const args = buildPackagePlaylistArgs(sanitizedPayload);
    const label = `Package playlist: ${sanitizedPayload.playlist}`;

    const taskId = await createTask(label, args);

    return { taskId };
  });

  ipcMain.handle('onepiece/shotgrid-show-setup', async (_event, payload: ShowSetupPayload) => {
    const sanitizedPayload: ShowSetupPayload = {
      csvPath: trimRequired(payload.csvPath, 'csvPath'),
      project: trimRequired(payload.project, 'project'),
      template: trimOptional(payload.template, 'template'),
    };

    const args = buildShowSetupArgs(sanitizedPayload);
    return runCommand(args);
  });

  ipcMain.handle('onepiece/shotgrid-deliver', async (_event, payload: DeliverPayload) => {
    const sanitizedPayload: DeliverPayload = {
      project: trimRequired(payload.project, 'project'),
      context: trimRequired(payload.context, 'context'),
      output: trimRequired(payload.output, 'output'),
      episodes: normalizeEpisodes(payload.episodes),
      manifest: trimOptional(payload.manifest, 'manifest'),
    };

    const args = buildDeliverArgs(sanitizedPayload);
    const label = `ShotGrid delivery: ${sanitizedPayload.project}`;

    const taskId = await createTask(label, args);

    return { taskId };
  });
}
