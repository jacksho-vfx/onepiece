import type { BrowserWindow, IpcMain } from 'electron';
import { createTask } from './taskManager';

type AwsSyncDirection = 'from' | 'to';

type AwsSyncPayload = {
  direction: AwsSyncDirection;
  localPath: string;
  bucketUrl: string;
  extraArgs?: string[];
};

const buildArgs = ({ direction, localPath, bucketUrl, extraArgs = [] }: AwsSyncPayload): string[] => {
  return [
    '-m',
    'onepiece',
    'aws',
    direction === 'from' ? 'sync-from' : 'sync-to',
    localPath,
    bucketUrl,
    ...extraArgs,
  ];
};

const buildLabel = ({ direction, bucketUrl }: AwsSyncPayload): string => {
  const target = bucketUrl || 'bucket';
  return direction === 'from'
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
