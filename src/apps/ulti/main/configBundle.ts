import { spawn } from 'child_process';
import { promises as fs, createWriteStream } from 'fs';
import os from 'os';
import path from 'path';
import { pipeline } from 'stream/promises';
import yauzl from 'yauzl';
import type { App, BrowserWindow, IpcMain } from 'electron';
import { dialog } from 'electron';
import {
  ensureDefaultConfig,
  getConfigPath,
  saveConfig,
  type DesktopConfig,
} from './configManager';

async function copyFileIfExists(source: string, destination: string): Promise<boolean> {
  try {
    await fs.access(source);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  }

  await fs.mkdir(path.dirname(destination), { recursive: true });
  await fs.copyFile(source, destination);
  return true;
}

async function copyDirectoryRecursive(source: string, destination: string): Promise<void> {
  await fs.mkdir(destination, { recursive: true });
  const entries = await fs.readdir(source, { withFileTypes: true });

  for (const entry of entries) {
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);

    if (entry.isDirectory()) {
      await copyDirectoryRecursive(sourcePath, destinationPath);
    } else if (entry.isFile()) {
      await copyFileIfExists(sourcePath, destinationPath);
    }
    // TODO: Handle symlinks or other file types if the project configuration requires them.
  }
}

async function copyDirectoryIfExists(source: string, destination: string): Promise<boolean> {
  let stats: Awaited<ReturnType<typeof fs.stat>>;
  try {
    stats = await fs.stat(source);
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return false;
    throw error;
  }

  if (!stats.isDirectory()) {
    return false;
  }

  await copyDirectoryRecursive(source, destination);
  return true;
}

function resolveProjectRoot(config: DesktopConfig): string | undefined {
  if (config.projectRoot && config.projectRoot.trim()) {
    return config.projectRoot.trim();
  }

  if (config.currentProject && config.currentProject.trim()) {
    return config.currentProject.trim();
  }

  const recent = config.recentProjects?.find((project) => project.path?.trim());
  return recent?.path?.trim();
}

function isSymlinkEntry(entry: yauzl.Entry): boolean {
  const fileType = (entry.externalFileAttributes ?? 0) >>> 16;
  return (fileType & 0o170000) === 0o120000;
}

function resolveExtractPath(baseDir: string, entryPath: string): string {
  const normalized = path.normalize(entryPath);

  if (path.isAbsolute(normalized) || normalized.startsWith('..')) {
    throw new Error(`Blocked unsafe path in archive entry: ${entryPath}`);
  }

  const targetPath = path.join(baseDir, normalized);
  const relative = path.relative(baseDir, targetPath);

  if (relative.startsWith('..') || path.isAbsolute(relative)) {
    throw new Error(`Blocked path traversal attempt for entry: ${entryPath}`);
  }

  return targetPath;
}

export async function extractConfigBundleArchive(zipPath: string, destination: string): Promise<void> {
  await new Promise<void>((resolve, reject) => {
    yauzl.open(zipPath, { lazyEntries: true }, (err, zipfile) => {
      if (err || !zipfile) {
        reject(err ?? new Error('Unable to open zip archive'));
        return;
      }

      zipfile.readEntry();

      zipfile.on('entry', (entry) => {
        void (async () => {
          try {
            if (isSymlinkEntry(entry)) {
              throw new Error(`Blocked symlink entry: ${entry.fileName}`);
            }

            const targetPath = resolveExtractPath(destination, entry.fileName);

            if (entry.fileName.endsWith('/')) {
              await fs.mkdir(targetPath, { recursive: true });
              zipfile.readEntry();
              return;
            }

            await fs.mkdir(path.dirname(targetPath), { recursive: true });

            zipfile.openReadStream(entry, async (streamError, readStream) => {
              if (streamError || !readStream) {
                zipfile.close();
                reject(streamError ?? new Error(`Failed to read entry: ${entry.fileName}`));
                return;
              }

              try {
                await pipeline(readStream, createWriteStream(targetPath));
                zipfile.readEntry();
              } catch (pipelineError) {
                zipfile.close();
                reject(pipelineError);
              }
            });
          } catch (processingError) {
            zipfile.close();
            reject(processingError);
          }
        })();
      });

      zipfile.on('end', resolve);
      zipfile.on('error', reject);
    });
  });
}

async function pathExists(targetPath: string): Promise<boolean> {
  try {
    await fs.access(targetPath);
    return true;
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') {
      return false;
    }
    throw error;
  }
}

async function copyFileWithBackup(source: string, destination: string): Promise<void> {
  await fs.mkdir(path.dirname(destination), { recursive: true });

  if (await pathExists(destination)) {
    let backupPath = `${destination}.bak`;
    let counter = 1;

    while (await pathExists(backupPath)) {
      backupPath = `${destination}.bak.${counter}`;
      counter += 1;
    }

    await fs.rename(destination, backupPath);
  }

  await fs.copyFile(source, destination);
}

async function copyDirectoryWithBackup(source: string, destination: string): Promise<void> {
  await fs.mkdir(destination, { recursive: true });
  const entries = await fs.readdir(source, { withFileTypes: true });

  for (const entry of entries) {
    const sourcePath = path.join(source, entry.name);
    const destinationPath = path.join(destination, entry.name);

    if (entry.isDirectory()) {
      await copyDirectoryWithBackup(sourcePath, destinationPath);
    } else if (entry.isFile()) {
      await copyFileWithBackup(sourcePath, destinationPath);
    }
  }
}

async function zipDirectory(sourceDir: string): Promise<string> {
  const zipPath = path.join(os.tmpdir(), `onepiece-config-bundle-${Date.now()}.zip`);

  // TODO: Replace with a Node zip library (e.g. archiver) for better portability and streaming.
  await new Promise<void>((resolve, reject) => {
    const child = spawn('zip', ['-r', zipPath, '.'], { cwd: sourceDir });

    let errorOutput = '';
    child.stderr?.on('data', (data) => {
      errorOutput += data.toString();
    });

    child.on('error', (error) => {
      reject(error);
    });

    child.on('close', (code) => {
      if (code === 0) {
        resolve();
      } else {
        reject(new Error(errorOutput || `Zip command failed with exit code ${code}`));
      }
    });
  });

  return zipPath;
}

export async function createConfigBundle(app: App): Promise<string> {
  const config = await ensureDefaultConfig(app);
  const stagingDir = await fs.mkdtemp(path.join(os.tmpdir(), 'onepiece-config-bundle-'));

  try {
    await fs.writeFile(path.join(stagingDir, 'main-config.json'), JSON.stringify(config, null, 2), 'utf-8');
    await copyFileIfExists(getConfigPath(app), path.join(stagingDir, 'main-config.raw.json'));

    const projectRoot = resolveProjectRoot(config);
    if (projectRoot) {
      const projectDestination = path.join(stagingDir, 'project');
      await fs.mkdir(projectDestination, { recursive: true });

      await copyFileIfExists(path.join(projectRoot, 'onepiece.toml'), path.join(projectDestination, 'onepiece.toml'));
      await copyDirectoryIfExists(path.join(projectRoot, 'profiles'), path.join(projectDestination, 'profiles'));
      // TODO: Copy any additional starter-kit or project-level configuration files that need to be
      // included in the export bundle once the file list is finalized.
    }

    const zipPath = await zipDirectory(stagingDir);
    return zipPath;
  } finally {
    await fs.rm(stagingDir, { recursive: true, force: true });
  }
}

export async function importConfigBundle(app: App, bundlePath: string): Promise<void> {
  const stagingDir = await fs.mkdtemp(path.join(os.tmpdir(), 'onepiece-config-import-'));

  try {
    await extractConfigBundleArchive(bundlePath, stagingDir);

    const desktopConfigPath = path.join(stagingDir, 'main-config.json');
    if (!(await pathExists(desktopConfigPath))) {
      throw new Error('The bundle is missing main-config.json');
    }

    const importedConfig = JSON.parse(await fs.readFile(desktopConfigPath, 'utf-8')) as DesktopConfig;
    const existingConfig = await ensureDefaultConfig(app);

    const mergedConfig: DesktopConfig = {
      ...existingConfig,
      ...importedConfig,
      pythonPath: existingConfig.pythonPath,
      dccs: existingConfig.dccs,
      projectRoot: existingConfig.projectRoot ?? importedConfig.projectRoot,
      currentProject: existingConfig.currentProject ?? importedConfig.currentProject,
      recentProjects: existingConfig.recentProjects ?? importedConfig.recentProjects,
      createdAt: existingConfig.createdAt,
      updatedAt: new Date().toISOString(),
    };

    const projectBundlePath = path.join(stagingDir, 'project');
    const targetProjectRoot = resolveProjectRoot(mergedConfig) ?? resolveProjectRoot(importedConfig);

    if (await pathExists(projectBundlePath)) {
      if (!targetProjectRoot) {
        console.warn('Project files found in bundle, but no project root is configured. Skipping copy.');
      } else {
        await fs.mkdir(targetProjectRoot, { recursive: true });

        const bundledToml = path.join(projectBundlePath, 'onepiece.toml');
        if (await pathExists(bundledToml)) {
          await copyFileWithBackup(bundledToml, path.join(targetProjectRoot, 'onepiece.toml'));
        }

        const bundledProfiles = path.join(projectBundlePath, 'profiles');
        if (await pathExists(bundledProfiles)) {
          await copyDirectoryWithBackup(bundledProfiles, path.join(targetProjectRoot, 'profiles'));
        }
      }
    }

    await saveConfig(app, mergedConfig);
  } finally {
    await fs.rm(stagingDir, { recursive: true, force: true });
  }
}

export function registerConfigBundleIpcHandlers(
  ipcMain: IpcMain,
  app: App,
  window?: BrowserWindow,
): void {
  ipcMain.handle('config/export-bundle', async () => {
    const bundlePath = await createConfigBundle(app);

    try {
      const { canceled, filePath } = await dialog.showSaveDialog(window, {
        title: 'Export studio config bundle',
        defaultPath: path.join(app.getPath('documents'), 'onepiece-config-bundle.zip'),
        filters: [{ name: 'Zip archive', extensions: ['zip'] }],
      });

      if (canceled || !filePath) {
        throw new Error('Export cancelled');
      }

      await fs.copyFile(bundlePath, filePath);
      return filePath;
    } finally {
      await fs.rm(bundlePath, { force: true });
    }
  });

  ipcMain.handle('config/import-bundle', async () => {
    const { canceled, filePaths } = await dialog.showOpenDialog(window, {
      title: 'Import studio config bundle',
      properties: ['openFile'],
      filters: [{ name: 'Zip archive', extensions: ['zip'] }],
    });

    if (canceled || !filePaths?.length) {
      throw new Error('Import cancelled');
    }

    const bundlePath = filePaths[0];
    await importConfigBundle(app, bundlePath);
    return true;
  });
}
