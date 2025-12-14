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
import { detectDccExecutables } from './envDetection';

const DCC_KEYS = ['maya', 'blender', 'unreal'] as const;

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
    showCode: z.string().optional(),
    remotePath: z.string().optional(),
  })
  .strict();

const dccSchema = z
  .object({
    enabled: z.boolean(),
    executablePath: z.string().optional(),
  })
  .strict();

const serviceProfileSchema = z
  .object({
    key: z.string(),
    name: z.string(),
    description: z.string().optional(),
    args: z.array(z.string()),
    persistent: z.boolean().optional(),
  })
  .strict();

const servicesConfigSchema = z
  .object({
    profiles: z.array(serviceProfileSchema),
    enabled: z.record(z.string(), z.boolean()).optional(),
  })
  .strict();

const DEFAULT_SERVICE_PROFILES: z.infer<typeof serviceProfileSchema>[] = [
  {
    key: 'trafalgar',
    name: 'Trafalgar',
    description: 'Asset management and pipeline orchestration.',
    args: ['-m', 'apps.trafalgar'],
    persistent: true,
  },
  {
    key: 'perona',
    name: 'Perona',
    description: 'Perona dashboard web service.',
    args: ['-m', 'apps.perona'],
    persistent: true,
  },
  {
    key: 'uta',
    name: 'Uta Control Center',
    description: 'Monitoring and operations control center.',
    args: ['-m', 'apps.uta'],
    persistent: true,
  },
  {
    key: 'tester',
    name: 'Tester Demo Stack',
    description: 'Demo stack for validation and testing.',
    args: ['-m', 'apps.tester'],
  },
];

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
    services: servicesConfigSchema.optional(),
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

function mergeDccConfig(
  existing: DesktopConfig['dccs'],
  detected: ReturnType<typeof detectDccExecutables>,
): { dccs?: DesktopConfig['dccs']; changed: boolean } {
  const dccs: NonNullable<DesktopConfig['dccs']> = existing ? { ...existing } : {};
  let changed = false;

  for (const key of DCC_KEYS) {
    const current = dccs[key];
    const detectedPath = detected[key];
    const hasCurrentPath = Boolean(current?.executablePath?.trim());

    if (detectedPath && !hasCurrentPath) {
      dccs[key] = {
        enabled: true,
        executablePath: detectedPath,
      };
      changed = true;
      continue;
    }

    if (!current) {
      dccs[key] = { enabled: false, executablePath: undefined };
      changed = true;
    }
  }

  return { dccs, changed };
}

type ServicesConfig = z.infer<typeof servicesConfigSchema>;

function ensureServiceConfig(
  existing?: DesktopConfig['services'],
): { services: ServicesConfig; changed: boolean } {
  let changed = false;

  const profileByKey = new Map<string, z.infer<typeof serviceProfileSchema>>();
  const normalizedProfiles: z.infer<typeof serviceProfileSchema>[] = [];

  const existingProfiles = existing?.profiles ?? [];
  for (const profile of existingProfiles) {
    if (!profileByKey.has(profile.key)) {
      profileByKey.set(profile.key, profile);
      normalizedProfiles.push(profile);
    }
  }

  for (const defaultProfile of DEFAULT_SERVICE_PROFILES) {
    if (!profileByKey.has(defaultProfile.key)) {
      normalizedProfiles.push(defaultProfile);
      changed = true;
    }
  }

  const enabledDefaults = DEFAULT_SERVICE_PROFILES.reduce<Record<string, boolean>>((acc, profile) => {
    acc[profile.key] = Boolean(profile.persistent);
    return acc;
  }, {});

  const enabled = { ...enabledDefaults, ...(existing?.enabled ?? {}) };

  return {
    services: {
      profiles: normalizedProfiles,
      enabled,
    },
    changed,
  };
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
    const detectedDccs = detectDccExecutables();
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

    const { dccs: normalizedDccs, changed: dccsChanged } = mergeDccConfig(existing.dccs, detectedDccs);
    if (dccsChanged) {
      existing.dccs = normalizedDccs;
      needsSave = true;
    }

    const { services, changed: servicesChanged } = ensureServiceConfig(existing.services);
    if (servicesChanged || !existing.services) {
      existing.services = services;
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
  const detectedDccs = detectDccExecutables();
  const defaultConfig: DesktopConfig = {
    hasCompletedWizard: false,
    createdAt: now,
    updatedAt: now,
    enableNotifications: true,
    dccs: mergeDccConfig(undefined, detectedDccs).dccs,
    services: ensureServiceConfig(undefined).services,
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

      const normalizedExistingServices = ensureServiceConfig(existing.services).services;
      const mergedServices = (() => {
        if (!updates.services) {
          return normalizedExistingServices;
        }

        const profiles = updates.services.profiles ?? normalizedExistingServices.profiles;
        const enabled = { ...normalizedExistingServices.enabled, ...(updates.services.enabled ?? {}) };

        return ensureServiceConfig({ profiles, enabled }).services;
      })();

      const updatedConfig: DesktopConfig = {
        ...existing,
        ...updates,
        quickActionPresets: mergedQuickActionPresets,
        services: mergedServices,
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
