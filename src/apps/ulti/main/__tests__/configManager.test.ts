import { promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

vi.mock('electron', () => ({
  app: { getPath: vi.fn() },
  dialog: {},
  BrowserWindow: class {},
  ipcMain: {},
}));

import type { App } from 'electron';

import { ensureDefaultConfig, getConfigPath } from '../configManager';
import * as envDetection from '../envDetection';

const detectSpy = vi.spyOn(envDetection, 'detectDccExecutables');

describe('ensureDefaultConfig', () => {
  let userDataDir: string;
  let app: App;

  beforeEach(async () => {
    userDataDir = await fs.mkdtemp(path.join(os.tmpdir(), 'config-manager-test-'));
    app = { getPath: vi.fn().mockReturnValue(userDataDir) } as unknown as App;
  });

  afterEach(async () => {
    detectSpy.mockReset();
    await fs.rm(userDataDir, { recursive: true, force: true });
  });

  it('seeds missing DCC executable paths with detected values', async () => {
    detectSpy.mockReturnValue({
      maya: '/opt/Autodesk/maya',
      blender: undefined,
      unreal: '/opt/UnrealEngine/Engine/Binaries/Linux/UnrealEditor',
    });

    const config = await ensureDefaultConfig(app);

    expect(config.dccs?.maya).toEqual({ enabled: true, executablePath: '/opt/Autodesk/maya' });
    expect(config.dccs?.unreal).toEqual({
      enabled: true,
      executablePath: '/opt/UnrealEngine/Engine/Binaries/Linux/UnrealEditor',
    });
    expect(config.dccs?.blender?.enabled).toBe(false);
    expect(config.dccs?.blender?.executablePath).toBeUndefined();

    const persisted = JSON.parse(await fs.readFile(getConfigPath(app), 'utf-8'));
    expect(persisted.dccs.maya.executablePath).toBe('/opt/Autodesk/maya');
  });

  it('preserves existing DCC settings while filling gaps', async () => {
    detectSpy.mockReturnValue({
      maya: '/detected/maya',
      blender: '/detected/blender',
      unreal: undefined,
    });

    const configPath = getConfigPath(app);
    await fs.mkdir(path.dirname(configPath), { recursive: true });
    const existing = {
      hasCompletedWizard: true,
      createdAt: new Date().toISOString(),
      updatedAt: new Date().toISOString(),
      enableNotifications: true,
      dccs: {
        maya: { enabled: false, executablePath: '/custom/maya' },
      },
    };

    await fs.writeFile(configPath, JSON.stringify(existing));

    const config = await ensureDefaultConfig(app);

    expect(config.dccs?.maya?.executablePath).toBe('/custom/maya');
    expect(config.dccs?.maya?.enabled).toBe(false);
    expect(config.dccs?.blender?.executablePath).toBe('/detected/blender');
    expect(config.dccs?.blender?.enabled).toBe(true);
    expect(config.dccs?.unreal?.enabled).toBe(false);
  });
});

