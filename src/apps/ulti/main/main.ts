import { app, BrowserWindow, Menu, MenuItemConstructorOptions, dialog, ipcMain, shell } from 'electron';
import path from 'path';
import { registerConfigIpcHandlers } from './configManager';
import { registerConfigBundleIpcHandlers } from './configBundle';
import { registerFsExplorerIpcHandlers } from './fsExplorer';
import { registerPythonIpcHandlers } from './pythonManager';
import { registerEnvIpcHandlers } from './envDetection';
import { registerVersionIpcHandlers } from './versionInfo';
import { registerUpdateIpcHandlers } from './updateCheck';
import { registerTaskIpcHandlers } from './taskManager';
import { createTray } from './tray';
import { registerAwsSyncIpcHandlers } from './awsSync';
import { registerShotgridIpcHandlers } from './shotgrid';
import { registerPeronaIpcHandlers } from './perona';
import { registerTrafalgarPipelineIpcHandlers } from './trafalgar';
import { registerChopperIpcHandlers } from './chopper';
import { registerRenderIpcHandlers } from './render';
import { ensureSafeExternalUrl } from './url';
import { buildMenuTemplate } from './menuTemplate';
import { getPythonBundleSearchPaths, validatePythonBundle } from './pythonBundleValidator';

// Detect whether we are running in development mode (served by Vite) or production
// (loading the bundled renderer output). This assumes the build pipeline outputs
// renderer assets alongside the compiled main process files.
const isDevelopment = process.env.NODE_ENV === 'development';
const allowDeveloperTools = isDevelopment || process.env.ENABLE_DEVTOOLS_MENU === 'true';

let mainWindow: BrowserWindow | null = null;

async function ensurePythonPayloadReady(): Promise<boolean> {
  const searchPaths = getPythonBundleSearchPaths(app);

  while (true) {
    const validation = await validatePythonBundle(searchPaths);

    if (validation.status === 'valid') {
      console.info('Python payload validated', {
        bundlePath: validation.attempt.bundlePath,
        manifest: validation.attempt.manifest,
      });
      return true;
    }

    console.error('Python payload validation failed', validation.attempts);

    const detail = validation.attempts
      .map((attempt) => {
        const missing = attempt.missing.length > 0 ? `Missing: ${attempt.missing.join(', ')}` : null;
        const error = attempt.error ? `Error: ${attempt.error}` : null;
        const parts = [missing, error].filter(Boolean);
        const manifestSource = attempt.manifest?.runtimeSource || attempt.manifest?.wheelsSource;
        const sourceLine = manifestSource ? `Source: ${manifestSource}` : null;

        if (sourceLine) {
          parts.unshift(sourceLine);
        }

        return [attempt.bundlePath, ...parts].filter(Boolean).join('\n');
      })
      .join('\n\n');

    const { response } = await dialog.showMessageBox({
      type: 'error',
      title: 'Python payload required',
      message: 'OnePiece Studio Desktop is missing its bundled Python runtime.',
      detail:
        'Please supply the runtime, wheels, and DCC directories referenced in python/manifest.json, then click Retry.' +
        (detail ? `\n\n${detail}` : ''),
      buttons: ['Retry', 'Quit'],
      defaultId: 0,
      cancelId: 1,
      noLink: true,
    });

    if (response !== 0) {
      app.quit();
      return false;
    }
  }
}

/**
 * Create the primary application window.
 */
function createMainWindow(): BrowserWindow {
  mainWindow = new BrowserWindow({
    title: 'OnePiece Studio Desktop',
    width: 1200,
    height: 800,
    minWidth: 1024,
    minHeight: 700,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      sandbox: true,
      nodeIntegration: false,
      webviewTag: false,
    },
  });

  if (isDevelopment) {
    // During development we expect Vite to be serving the renderer on localhost:5173.
    void mainWindow.loadURL('http://localhost:5173');
  } else {
    // In production load the bundled renderer HTML. Adjust the path if your build output changes.
    const indexPath = path.join(__dirname, '../renderer/index.html');
    void mainWindow.loadFile(indexPath);
  }

  // Wire up the application menu once the window exists so the handlers can reference it.
  const menuTemplate: MenuItemConstructorOptions[] = buildMenuTemplate({
    allowDevTools: allowDeveloperTools,
    mainWindow,
  }) as MenuItemConstructorOptions[];

  const menu = Menu.buildFromTemplate(menuTemplate);
  Menu.setApplicationMenu(menu);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

// Create the window and wire IPC handlers once Electron is ready.
app.whenReady().then(async () => {
  const payloadReady = await ensurePythonPayloadReady();
  if (!payloadReady) {
    return;
  }

  const window = createMainWindow();
  registerPythonIpcHandlers(ipcMain, window, app);
  registerConfigIpcHandlers(ipcMain, app);
  registerConfigBundleIpcHandlers(ipcMain, app, window);
  registerEnvIpcHandlers(ipcMain);
  registerVersionIpcHandlers(ipcMain, app);
  registerUpdateIpcHandlers(ipcMain, app);
  registerTaskIpcHandlers(ipcMain, window, app);
  registerRenderIpcHandlers();
  registerFsExplorerIpcHandlers(ipcMain);
  registerAwsSyncIpcHandlers(ipcMain, window);
  registerShotgridIpcHandlers(ipcMain, window);
  registerPeronaIpcHandlers(ipcMain);
  registerTrafalgarPipelineIpcHandlers(ipcMain);
  registerChopperIpcHandlers(ipcMain);
  createTray(window);
  ipcMain.handle('open-url', async (_event, payload: string | { url: string }) => {
    const requestedUrl = typeof payload === 'string' ? payload : payload.url;
    const safeUrl = ensureSafeExternalUrl(requestedUrl);
    await shell.openExternal(safeUrl);
  });
});

// Quit the application when all windows are closed on platforms other than macOS.
app.on('window-all-closed', () => {
  if (process.platform !== 'darwin') {
    app.quit();
  }
});

// Recreate a window when the dock icon is clicked and there are no open windows (macOS behaviour).
app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    createMainWindow();
  }
});
