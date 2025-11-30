import { promises as fs } from 'fs';
import path from 'path';
import type { App, IpcMain } from 'electron';

export interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  shotgrid?: {
    url?: string;
    scriptName?: string;
    apiKey?: string;
  };
  aws?: {
    accessKeyId?: string;
    secretAccessKey?: string;
    region?: string;
    defaultBucket?: string;
  };
}

export function getConfigPath(app: App): string {
  const userDataPath = app.getPath('userData');
  return path.join(userDataPath, 'desktop-config.json');
}

export async function loadConfig(app: App): Promise<DesktopConfig | null> {
  const configPath = getConfigPath(app);
  try {
    await fs.access(configPath);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT') {
      console.error('Error accessing desktop config:', error);
    }
    return null;
  }

  try {
    const content = await fs.readFile(configPath, 'utf-8');
    return JSON.parse(content) as DesktopConfig;
  } catch (error) {
    console.error('Error reading desktop config:', error);
    return null;
  }
}

export async function saveConfig(app: App, config: DesktopConfig): Promise<void> {
  const configPath = getConfigPath(app);
  const dir = path.dirname(configPath);
  try {
    await fs.mkdir(dir, { recursive: true });
    await fs.writeFile(configPath, JSON.stringify(config, null, 2), 'utf-8');
  } catch (error) {
    console.error('Error saving desktop config:', error);
    throw error;
  }
}

export async function ensureDefaultConfig(app: App): Promise<DesktopConfig> {
  const existing = await loadConfig(app);
  if (existing) {
    let needsSave = false;
    if (!existing.createdAt) {
      existing.createdAt = new Date().toISOString();
      needsSave = true;
    }
    if (!existing.updatedAt) {
      existing.updatedAt = existing.createdAt;
      needsSave = true;
    }

    if (needsSave) {
      try {
        await saveConfig(app, existing);
      } catch (error) {
        console.error('Error persisting normalized desktop config:', error);
      }
    }
    return existing;
  }

  const now = new Date().toISOString();
  const defaultConfig: DesktopConfig = {
    hasCompletedWizard: false,
    createdAt: now,
    updatedAt: now,
  };

  try {
    await saveConfig(app, defaultConfig);
  } catch (error) {
    console.error('Error saving default desktop config:', error);
  }

  return defaultConfig;
}

export function registerConfigIpcHandlers(ipcMain: IpcMain, app: App): void {
  ipcMain.handle('config/get', async () => ensureDefaultConfig(app));

  ipcMain.handle(
    'config/save',
    async (_event, updates: Partial<DesktopConfig>): Promise<DesktopConfig> => {
      const existing = await ensureDefaultConfig(app);
      const now = new Date().toISOString();

      const updatedConfig: DesktopConfig = {
        ...existing,
        ...updates,
        createdAt: existing.createdAt || now,
        updatedAt: now,
      };

      try {
        await saveConfig(app, updatedConfig);
      } catch (error) {
        console.error('Error persisting updated desktop config:', error);
        throw error;
      }

      return updatedConfig;
    },
  );
}
