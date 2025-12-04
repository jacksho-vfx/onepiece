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
  const trimmedRemote = remote.trim();

  if (!trimmedRemote) {
    throw new Error("Remote path is required, e.g. 's3://bucket/show/path'.");
  }

  const withoutScheme = trimmedRemote.replace(/^s3:\/\//i, '');
  const [bucket, showCode, ...remainingSegments] = withoutScheme.split('/').filter(Boolean);

  if (!bucket) {
    throw new Error("Remote path must include an S3 bucket, e.g. 's3://bucket/show/path'.");
  }

  if (!showCode) {
    throw new Error(
      "Remote path must include a show code after the bucket, e.g. 's3://bucket/show/path'.",
    );
  }

  const folder = remainingSegments.join('/');

  if (!folder) {
    throw new Error(
      "Remote path must include a folder/prefix after the show code, e.g. 's3://bucket/show/path'.",
    );
  }

  return {
    bucket,
    showCode,
    folder,
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
    const trimmedLocalPath = payload.localPath?.trim();
    const trimmedRemote = payload.remote?.trim();

    if (!trimmedLocalPath) {
      throw new Error('A local path is required to run AWS sync.');
    }

    if (!trimmedRemote) {
      throw new Error("A remote path is required, e.g. 's3://bucket/show/path'.");
    }

    const normalizedPayload: AwsSyncPayload = {
      ...payload,
      localPath: trimmedLocalPath,
      remote: trimmedRemote,
      extraArgs: payload.extraArgs ?? [],
    };

    const args = buildArgs(normalizedPayload);
    const label = buildLabel(normalizedPayload);

    return createTask(label, args);
  });
}
