import fs from 'fs';
import path from 'path';
import {
  BrowserWindow,
  Menu,
  MenuItemConstructorOptions,
  Tray,
  app,
  type NativeImage,
  nativeImage,
} from 'electron';
import {
  listServices,
  onServicesChanged,
  startService,
  stopService,
  type ServiceSummary,
} from './pythonManager';

interface CoreServiceDefinition {
  key: 'trafalgar' | 'perona' | 'uta';
  name: string;
  args: string[];
}

const CORE_SERVICES: CoreServiceDefinition[] = [
  { key: 'trafalgar', name: 'Trafalgar', args: ['-m', 'apps.trafalgar'] },
  { key: 'perona', name: 'Perona', args: ['-m', 'apps.perona'] },
  { key: 'uta', name: 'Uta', args: ['-m', 'apps.uta'] },
];

let tray: Tray | null = null;
let unsubscribeFromServices: (() => void) | null = null;
let cachedServices: ServiceSummary[] = [];

function resolveTrayIcon(): NativeImage {
  const iconCandidates = [
    path.join(process.resourcesPath, 'icon.png'),
    path.join(app.getAppPath(), 'build', 'icon.png'),
    path.join(app.getAppPath(), 'dist', 'icon.png'),
    path.join(__dirname, 'icon.png'),
  ];

  for (const candidate of iconCandidates) {
    if (fs.existsSync(candidate)) {
      const image = nativeImage.createFromPath(candidate);
      if (!image.isEmpty()) {
        return image;
      }
    }
  }

  return nativeImage.createEmpty();
}

function getRunningCoreServices(services: ServiceSummary[]): Map<CoreServiceDefinition['key'], string> {
  const running = new Map<CoreServiceDefinition['key'], string>();
  services.forEach((service) => {
    const definition = CORE_SERVICES.find((candidate) => candidate.name === service.name);
    if (definition) {
      running.set(definition.key, service.id);
    }
  });
  return running;
}

function updateTooltip(currentServices: ServiceSummary[]): void {
  const runningCoreServices = getRunningCoreServices(currentServices);
  const allRunning = runningCoreServices.size === CORE_SERVICES.length;
  const tooltip = allRunning
    ? 'OnePiece Studio Desktop – Services running'
    : runningCoreServices.size === 0
      ? 'OnePiece Studio Desktop – Services stopped'
      : 'OnePiece Studio Desktop – Some services are stopped';

  tray?.setToolTip(tooltip);
}

async function startCoreServices(): Promise<void> {
  const running = getRunningCoreServices(cachedServices);

  for (const service of CORE_SERVICES) {
    if (running.has(service.key)) {
      continue;
    }

    try {
      await startService(service.name, service.args);
    } catch (error) {
      console.error(`Failed to start service ${service.name}`, error);
    }
  }

  cachedServices = listServices();
  updateTooltip(cachedServices);
}

async function stopCoreServices(): Promise<void> {
  const running = getRunningCoreServices(cachedServices);

  for (const [key, id] of running.entries()) {
    const serviceName = CORE_SERVICES.find((service) => service.key === key)?.name ?? key;
    try {
      await stopService(id);
    } catch (error) {
      console.error(`Failed to stop service ${serviceName}`, error);
    }
  }

  cachedServices = listServices();
  updateTooltip(cachedServices);
}

export function createTray(mainWindow: BrowserWindow): Tray {
  if (tray) {
    return tray;
  }

  tray = new Tray(resolveTrayIcon());
  cachedServices = listServices();
  updateTooltip(cachedServices);

  const focusOrShowWindow = (): void => {
    if (mainWindow.isDestroyed()) {
      return;
    }

    if (mainWindow.isMinimized()) {
      mainWindow.restore();
    }

    mainWindow.show();
    mainWindow.focus();
  };

  tray.on('click', focusOrShowWindow);

  const contextMenuTemplate: MenuItemConstructorOptions[] = [
    { label: 'Open OnePiece Studio Desktop', click: () => focusOrShowWindow() },
    { type: 'separator' },
    { label: 'Start Services', click: () => void startCoreServices() },
    { label: 'Stop Services', click: () => void stopCoreServices() },
    { type: 'separator' },
    { label: 'Quit', click: () => app.quit() },
  ];

  tray.setContextMenu(Menu.buildFromTemplate(contextMenuTemplate));

  const handleServicesChanged = (services: ServiceSummary[]): void => {
    cachedServices = services;
    updateTooltip(cachedServices);
  };

  // TODO: Replace this global cache with a dedicated state manager if more services are added.
  unsubscribeFromServices = onServicesChanged(handleServicesChanged);

  app.once('before-quit', () => {
    unsubscribeFromServices?.();
    tray?.destroy();
  });

  return tray;
}
