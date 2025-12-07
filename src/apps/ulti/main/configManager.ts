import { promises as fs } from 'fs';
import path from 'path';
import { z } from 'zod';
import type { App, IpcMain, IpcMainInvokeEvent } from 'electron';
import {
  generateOnepieceToml,
  installStarterKit,
  type StarterKitInstallResult,
  type WizardConfigInput,
} from './onepieceConfig';

const quickActionPresetsSchema = z
  .record(
    z.string(),
    z
      .object({
        vendorIngest: z.object({ sourcePath: z.string().optional() }).strict().optional(),
        dccPublish: z
          .object({ dccType: z.string().optional(), lastScenePath: z.string().optional() })
          .strict()
          .optional(),
        renderSubmit: z
          .object({ profileName: z.string().optional(), lastFrameRange: z.string().optional() })
          .strict()
          .optional(),
        clientDelivery: z
          .object({ playlistName: z.string().optional(), targetPath: z.string().optional() })
          .strict()
          .optional(),
      })
      .strict(),
  )
  .optional();

const awsSyncPresetSchema = z
  .object({
    id: z.string(),
    name: z.string(),
    direction: z.enum(['download', 'upload', 'from', 'to']),
    localPath: z.string(),
    remote: z.string().optional(),
    bucketUrl: z.string().optional(),
  })
  .strict();

const dccSchema = z
  .object({
    enabled: z.boolean(),
    executablePath: z.string().optional(),
  })
  .strict();

export const DesktopConfigSchema = z
  .object({
    hasCompletedWizard: z.boolean(),
    createdAt: z.string(),
    updatedAt: z.string(),
    enableNotifications: z.boolean().optional(),
    profile: z.enum(['vfx', 'archviz', 'freelancer', 'demo']).optional(),
    pythonPath: z.string().optional(),
    includePipelineTemplates: z.boolean().optional(),
    projectRoot: z.string().optional(),
    currentProject: z.string().optional(),
    recentProjects: z
      .array(
        z
          .object({
            name: z.string(),
            path: z.string(),
            lastOpenedAt: z.string(),
          })
          .strict(),
      )
      .optional(),
    quickActionPresets: quickActionPresetsSchema,
    awsSyncPresets: z.array(awsSyncPresetSchema).optional(),
    shotgrid: z
      .object({
        url: z.string().optional(),
        scriptName: z.string().optional(),
        apiKey: z.string().optional(),
      })
      .strict()
      .optional(),
    aws: z
      .object({
        accessKeyId: z.string().optional(),
        secretAccessKey: z.string().optional(),
        region: z.string().optional(),
        defaultBucket: z.string().optional(),
      })
      .strict()
      .optional(),
    dccs: z
      .object({
        maya: dccSchema.optional(),
        blender: dccSchema.optional(),
        unreal: dccSchema.optional(),
      })
      .strict()
      .optional(),
  })
  .strict();

export type DesktopConfig = z.infer<typeof DesktopConfigSchema>;

export function validateDesktopConfig(input: unknown): DesktopConfig {
  const parsed = DesktopConfigSchema.safeParse(input);

  if (!parsed.success) {
    const formatted = parsed.error.issues
      .map((issue) => `${issue.path.join('.') || 'root'}: ${issue.message}`)
      .join('; ');

    throw new Error(`Invalid desktop config: ${formatted}`);
  }

  return parsed.data;
}

export function getConfigPath(app: App): string {
  const userDataPath = app.getPath('userData');
  return path.join(userDataPath, 'main-config.json');
}

export async function loadConfig(app: App): Promise<DesktopConfig | null> {
  const configPath = getConfigPath(app);
  try {
    await fs.access(configPath);
  } catch (error) {
    const code = (error as NodeJS.ErrnoException).code;
    if (code !== 'ENOENT') {
      console.error('Error accessing main config:', error);
    }
    return null;
  }

  try {
    const content = await fs.readFile(configPath, 'utf-8');
    return JSON.parse(content) as DesktopConfig;
  } catch (error) {
    console.error('Error reading main config:', error);
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
    console.error('Error saving main config:', error);
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

    if (existing.enableNotifications === undefined) {
      existing.enableNotifications = true;
      needsSave = true;
    }

    if (needsSave) {
      try {
        await saveConfig(app, existing);
      } catch (error) {
        console.error('Error persisting normalized main config:', error);
      }
    }
    return existing;
  }

  const now = new Date().toISOString();
  const defaultConfig: DesktopConfig = {
    hasCompletedWizard: false,
    createdAt: now,
    updatedAt: now,
    enableNotifications: true,
  };

  try {
    await saveConfig(app, defaultConfig);
  } catch (error) {
    console.error('Error saving default main config:', error);
  }

  return defaultConfig;
}

function sendStarterKitResult(event: IpcMainInvokeEvent, result: StarterKitInstallResult): void {
  try {
    event.sender.send('starter-kit/install-result', result);
  } catch (error) {
    console.error('Failed to notify renderer about starter kit installation:', error);
  }
}

function getStarterKitTarget(
  existing: DesktopConfig,
  updates: Partial<DesktopConfig>,
  hasNewlyCompletedWizard: boolean,
): string | null {
  const profile = updates.profile ?? existing.profile;
  if (!profile) {
    return null;
  }

  const projectRootCandidate = updates.projectRoot ?? existing.projectRoot;

  if (hasNewlyCompletedWizard && projectRootCandidate) {
    return projectRootCandidate;
  }

  if (updates.projectRoot && updates.projectRoot !== existing.projectRoot) {
    return updates.projectRoot;
  }

  if (
    updates.currentProject &&
    updates.currentProject !== existing.currentProject &&
    !existing.recentProjects?.some((project) => project.path === updates.currentProject)
  ) {
    return updates.currentProject;
  }

  return null;
}

export function registerConfigIpcHandlers(ipcMain: IpcMain, app: App): void {
  ipcMain.handle('config/get', async () => ensureDefaultConfig(app));

  ipcMain.handle(
    'config/save',
    async (event, updates: Partial<DesktopConfig>): Promise<DesktopConfig> => {
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
          const nextPreset = preset ?? {};
          merged[projectName] = {
            ...existingPreset,
            ...nextPreset,
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
        console.error('Error persisting updated main config:', error);
        throw error;
      }

      if (hasNewlyCompletedWizard && updatedConfig.projectRoot && updatedConfig.profile) {
        const wizardInput: WizardConfigInput = {
          profile: updatedConfig.profile,
          projectRoot: updatedConfig.projectRoot,
          pythonPath: updatedConfig.pythonPath,
          includePipelineTemplates: updatedConfig.includePipelineTemplates,
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
      }

      const starterKitTarget = getStarterKitTarget(existing, updates, hasNewlyCompletedWizard);

      if (starterKitTarget && updatedConfig.profile) {
        try {
          const result = await installStarterKit(updatedConfig.profile, starterKitTarget);
          sendStarterKitResult(event, result);
        } catch (error) {
          console.error('Error installing starter kit:', error);
          sendStarterKitResult(event, {
            status: 'failed',
            profile: updatedConfig.profile,
            target: starterKitTarget,
            message: 'Unexpected error installing starter kit.',
          });
        }
      }

      return updatedConfig;
    },
  );
}
