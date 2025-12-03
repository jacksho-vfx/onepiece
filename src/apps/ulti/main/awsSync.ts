import type { BrowserWindow, IpcMain } from 'electron';
import { createTask } from './taskManager';

type AwsSyncDirection = 'upload' | 'download';

type AwsSyncPayload = {
  direction: AwsSyncDirection;
  localPath: string;
  remote: string;
  extraArgs?: string[];
};

type ParsedRemote = {
  bucket: string;
  showCode: string;
  folder: string;
};

const parseRemotePath = (remote: string): ParsedRemote => {
  const withoutScheme = remote.replace(/^s3:\/\//i, '');
  const [bucket, ...pathSegments] = withoutScheme.split('/').filter(Boolean);

  if (!bucket || pathSegments.length === 0) {
    throw new Error("Remote path must include a bucket and prefix, e.g. 's3://bucket/show/path'.");
  }

  const [showCode, ...remaining] = pathSegments;

  return {
    bucket,
    showCode,
    folder: remaining.join('/'),
  };
};

const buildArgs = ({ direction, localPath, remote, extraArgs = [] }: AwsSyncPayload): string[] => {
  const { bucket, showCode, folder } = parseRemotePath(remote);

  return [
    '-m',
    'onepiece',
    'aws',
    direction === 'download' ? 'sync-from' : 'sync-to',
    bucket,
    showCode,
    folder,
    localPath,
    ...extraArgs,
  ];
};

const buildLabel = ({ direction, remote }: AwsSyncPayload): string => {
  const target = remote || 's3 destination';
  return direction === 'download'
    ? `AWS sync from ${target}`
    : `AWS sync to ${target}`;
};

export function registerAwsSyncIpcHandlers(ipcMain: IpcMain, _browserWindow: BrowserWindow): void {
  ipcMain.handle('onepiece/aws-sync', async (_event, payload: AwsSyncPayload) => {
    const args = buildArgs(payload);
    const label = buildLabel(payload);

    return createTask(label, args);
  });
}
