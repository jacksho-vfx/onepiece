import { app, BrowserWindow, Menu, MenuItemConstructorOptions, ipcMain, shell } from 'electron';
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

// Detect whether we are running in development mode (served by Vite) or production
// (loading the bundled renderer output). This assumes the build pipeline outputs
// renderer assets alongside the compiled main process files.
const isDevelopment = process.env.NODE_ENV === 'development';

let mainWindow: BrowserWindow | null = null;

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
      // Preload can be wired here once implemented to expose a safe API to the renderer.
      // preload: path.join(__dirname, 'preload.js'),
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
  const menuTemplate: MenuItemConstructorOptions[] = [
    {
      label: 'File',
      submenu: [
        {
          role: 'quit',
          label: 'Quit',
        },
      ],
    },
    {
      label: 'View',
      submenu: [
        { role: 'reload', label: 'Reload' },
        { role: 'toggleDevTools', label: 'Toggle Developer Tools' },
      ],
    },
    {
      label: 'Developer',
      submenu: [
        {
          label: 'Toggle Dev Tools',
          click: () => mainWindow?.webContents.toggleDevTools(),
        },
      ],
    },
  ];

  const menu = Menu.buildFromTemplate(menuTemplate);
  Menu.setApplicationMenu(menu);

  mainWindow.on('closed', () => {
    mainWindow = null;
  });

  return mainWindow;
}

// Create the window and wire IPC handlers once Electron is ready.
app.whenReady().then(() => {
  const window = createMainWindow();
  registerPythonIpcHandlers(ipcMain, window);
  registerConfigIpcHandlers(ipcMain, app);
  registerConfigBundleIpcHandlers(ipcMain, app, window);
  registerEnvIpcHandlers(ipcMain);
  registerVersionIpcHandlers(ipcMain, app);
  registerUpdateIpcHandlers(ipcMain, app);
  registerTaskIpcHandlers(ipcMain, window, app);
  registerFsExplorerIpcHandlers(ipcMain);
  registerAwsSyncIpcHandlers(ipcMain, window);
  registerShotgridIpcHandlers(ipcMain, window);
  registerPeronaIpcHandlers(ipcMain);
  createTray(window);
  ipcMain.handle('open-url', async (_event, payload: string | { url: string }) => {
    const url = typeof payload === 'string' ? payload : payload.url;
    if (!url) {
      throw new Error('No URL provided');
    }
    await shell.openExternal(url);
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
