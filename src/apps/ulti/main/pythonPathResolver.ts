import type { App } from 'electron';
import { ensureDefaultConfig } from './configManager';

let cachedPythonPath: string | null = null;
let configLoadPromise: Promise<void> | null = null;
let appForConfig: App | null = null;

function normalizePythonPath(value?: string | null): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

async function loadPythonPathFromConfig(): Promise<void> {
  if (!appForConfig) {
    return;
  }

  try {
    const config = await ensureDefaultConfig(appForConfig);
    const fromConfig = normalizePythonPath(config.pythonPath);

    if (fromConfig) {
      cachedPythonPath = fromConfig;
    }
  } catch (error) {
    console.error('Error loading pythonPath from config:', error);
  }
}

export function primePythonPath(app: App): void {
  appForConfig = app;
  cachedPythonPath = null;
  configLoadPromise = loadPythonPathFromConfig();
}

export async function resolvePythonPath(): Promise<string> {
  if (cachedPythonPath) {
    return cachedPythonPath;
  }

  if (configLoadPromise) {
    await configLoadPromise;
  } else if (appForConfig) {
    configLoadPromise = loadPythonPathFromConfig();
    await configLoadPromise;
  }

  const fallback = process.env.ONEPIECE_PYTHON_PATH || 'python';

  cachedPythonPath = cachedPythonPath || fallback;
  return cachedPythonPath;
}

export function resetPythonPathCacheForTesting(): void {
  cachedPythonPath = null;
  configLoadPromise = null;
  appForConfig = null;
}
