import { promises as fs } from 'fs';
import path from 'path';
import { dialog, shell, type IpcMain, type OpenDialogOptions } from 'electron';

export type FsNode = {
  path: string;
  name: string;
  isDir: boolean;
  children?: FsNode[];
};

const DEFAULT_DEPTH = 2;
const SKIPPED_NAMES = new Set(['.git', '.DS_Store', 'Thumbs.db', 'node_modules']);

function shouldSkipEntry(name: string): boolean {
  if (!name) {
    return true;
  }

  if (SKIPPED_NAMES.has(name)) {
    return true;
  }

  return name.startsWith('.');
}

async function buildNode(currentPath: string, maxDepth: number, currentDepth = 0): Promise<FsNode> {
  const stats = await fs.stat(currentPath);
  const isDir = stats.isDirectory();

  const node: FsNode = {
    path: currentPath,
    name: path.basename(currentPath),
    isDir,
  };

  if (!isDir || currentDepth >= maxDepth) {
    return node;
  }

  try {
    const dirents = await fs.readdir(currentPath, { withFileTypes: true });
    const children: FsNode[] = [];

    for (const dirent of dirents) {
      if (shouldSkipEntry(dirent.name)) {
        continue;
      }

      const childPath = path.join(currentPath, dirent.name);

      try {
        const childNode = await buildNode(childPath, maxDepth, currentDepth + 1);
        children.push(childNode);
      } catch (error) {
        console.warn(`Failed to read child path ${childPath}:`, error);
      }
    }

    if (children.length > 0) {
      node.children = children;
    }
  } catch (error) {
    console.warn(`Failed to read directory ${currentPath}:`, error);
  }

  return node;
}

export async function listDirectory(root: string, depth = DEFAULT_DEPTH): Promise<FsNode> {
  if (!root) {
    throw new Error('A root path is required to list directories.');
  }

  const normalizedDepth = Number.isFinite(depth) ? Math.max(0, Math.floor(depth)) : DEFAULT_DEPTH;
  const normalizedRoot = path.resolve(root);

  return buildNode(normalizedRoot, normalizedDepth);
}

export async function openInOs(targetPath: string): Promise<void> {
  if (!targetPath) {
    throw new Error('A path is required to open in the OS.');
  }

  try {
    const stats = await fs.stat(targetPath);
    if (stats.isDirectory()) {
      await shell.openPath(targetPath);
      return;
    }

    await shell.showItemInFolder(targetPath);
  } catch (error) {
    console.error(`Failed to open path in OS: ${targetPath}`, error);
    throw error;
  }
}

export function registerFsExplorerIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('fs/list-directory', async (_event, payload: { root: string; depth?: number }) => {
    const { root, depth } = payload ?? {};
    return listDirectory(root, depth);
  });

  ipcMain.handle('fs/open-in-os', async (_event, payload: string | { path: string }) => {
    const resolved = typeof payload === 'string' ? payload : payload?.path;
    if (!resolved) {
      throw new Error('No path provided to open.');
    }

    await openInOs(resolved);
    return true;
  });

  ipcMain.handle('dialog/open-file', async (_event, options?: OpenDialogOptions) => {
    const properties = new Set(options?.properties ?? []);
    properties.add('openFile');

    const dialogOptions: OpenDialogOptions = {
      properties: Array.from(properties),
      ...options,
    };

    const { canceled, filePaths } = await dialog.showOpenDialog(dialogOptions);
    if (canceled || !filePaths?.length) {
      return null;
    }

    return filePaths[0];
  });

  ipcMain.handle('dialog/open-folder', async (_event, options?: OpenDialogOptions) => {
    const properties = new Set(options?.properties ?? []);
    properties.add('openDirectory');
    properties.add('createDirectory');

    const dialogOptions: OpenDialogOptions = {
      properties: Array.from(properties),
      ...options,
    };

    const { canceled, filePaths } = await dialog.showOpenDialog(dialogOptions);
    if (canceled || !filePaths?.length) {
      return null;
    }

    return filePaths[0];
  });
}
