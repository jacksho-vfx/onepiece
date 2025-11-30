import type { App, IpcMain } from 'electron';
import { runCommand } from '../../pythonManager';

export function getDesktopVersion(app: App): string {
  return app.getVersion();
}

export async function getOnepieceVersion(): Promise<string | null> {
  try {
    const result = await runCommand(['-m', 'onepiece', '--version']);

    if (result.code !== 0) {
      return null;
    }

    const trimmedOutput = result.stdout.trim();
    if (!trimmedOutput) {
      return null;
    }

    const firstLine = trimmedOutput.split(/\r?\n/)[0];
    const versionMatch = firstLine.match(/(\d+(?:\.\d+)+(?:[^\s]*)?)/);

    if (versionMatch) {
      return versionMatch[1];
    }

    return firstLine;
  } catch (error) {
    console.error('Failed to retrieve OnePiece version', error);
    return null;
  }
}

export function registerVersionIpcHandlers(ipcMain: IpcMain, app: App): void {
  ipcMain.handle('version/get', async () => ({
    desktop: getDesktopVersion(app),
    onepiece: await getOnepieceVersion(),
  }));
}
