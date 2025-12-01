import { promises as fs } from 'fs';
import path from 'path';
import type { App, IpcMain } from 'electron';
import { generateOnepieceToml, installStarterKit, type WizardConfigInput } from './onepieceConfig';

export interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  currentProject?: string;
  recentProjects?: { name: string; path: string; lastOpenedAt: string }[];
  quickActionPresets?: {
    [projectName: string]: {
      vendorIngest?: { sourcePath?: string };
      dccPublish?: { dccType?: string; lastScenePath?: string };
      renderSubmit?: { profileName?: string; lastFrameRange?: string };
      clientDelivery?: { playlistName?: string; targetPath?: string };
    };
  };
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
  dccs?: {
    maya?: { enabled: boolean; executablePath?: string };
    blender?: { enabled: boolean; executablePath?: string };
    unreal?: { enabled: boolean; executablePath?: string };
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
      const hasNewlyCompletedWizard = !existing.hasCompletedWizard && updates.hasCompletedWizard === true;

      const mergedRecentProjects = (() => {
        if (Object.prototype.hasOwnProperty.call(updates, 'recentProjects')) {
          return updates.recentProjects;
        }
        return existing.recentProjects;
      })();

      const mergedCurrentProject = Object.prototype.hasOwnProperty.call(updates, 'currentProject')
        ? updates.currentProject
        : existing.currentProject;

      const mergedQuickActionPresets = (() => {
        if (!updates.quickActionPresets) {
          return existing.quickActionPresets;
        }

        const merged = { ...(existing.quickActionPresets ?? {}) };
        for (const [projectName, preset] of Object.entries(updates.quickActionPresets)) {
          const existingPreset = merged[projectName] ?? {};
          merged[projectName] = {
            ...existingPreset,
            ...preset,
          };
        }
        return merged;
      })();

      const updatedConfig: DesktopConfig = {
        ...existing,
        ...updates,
        quickActionPresets: mergedQuickActionPresets,
        currentProject: mergedCurrentProject,
        recentProjects: mergedRecentProjects,
        createdAt: existing.createdAt || now,
        updatedAt: now,
      };

      try {
        await saveConfig(app, updatedConfig);
      } catch (error) {
        console.error('Error persisting updated desktop config:', error);
        throw error;
      }

      if (hasNewlyCompletedWizard && updatedConfig.projectRoot && updatedConfig.profile) {
        const wizardInput: WizardConfigInput = {
          profile: updatedConfig.profile,
          projectRoot: updatedConfig.projectRoot,
          pythonPath: updatedConfig.pythonPath,
          shotgrid: updatedConfig.shotgrid,
          aws: updatedConfig.aws,
          dccs: updatedConfig.dccs,
        };

        const onepieceToml = generateOnepieceToml(wizardInput);
        const configDestination = path.join(updatedConfig.projectRoot, 'onepiece.toml');

        try {
          await fs.mkdir(updatedConfig.projectRoot, { recursive: true });
          await fs.writeFile(configDestination, onepieceToml, { encoding: 'utf-8', flag: 'wx' });
        } catch (error) {
          const code = (error as NodeJS.ErrnoException).code;
          if (code === 'EEXIST') {
            console.warn('onepiece.toml already exists at project root; skipping creation.');
          } else {
            console.error('Error writing onepiece.toml after wizard completion:', error);
          }
        }

        try {
          await installStarterKit(updatedConfig.profile, updatedConfig.projectRoot);
        } catch (error) {
          console.error('Error installing starter kit:', error);
        }
      }

      return updatedConfig;
    },
  );
}
