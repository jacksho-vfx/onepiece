import { ChildProcess, spawn } from 'child_process';
import { randomUUID } from 'crypto';
import type { BrowserWindow, IpcMain, WebContents } from 'electron';
import { createInterface } from 'readline';

/**
 * Represents a running Python service process.
 */
interface PythonService {
  id: string;
  name: string;
  process: ChildProcess;
}

export interface ServiceSummary {
  id: string;
  name: string;
  pid: number;
}

export interface LogEntry {
  serviceId: string;
  serviceName: string;
  stream: 'stdout' | 'stderr';
  line: string;
  timestamp: string;
}

/**
 * Resolve the interpreter to use for Python invocations.
 *
 * Currently reads from the environment variable `ONEPIECE_PYTHON_PATH`, falling
 * back to the default `python` executable if unset.
 */
const pythonPath = process.env.ONEPIECE_PYTHON_PATH || 'python';

/**
 * Track running Python services keyed by their generated id.
 */
const services = new Map<string, PythonService>();
const logBuffers = new Map<string, LogEntry[]>();
const LOG_BUFFER_LIMIT = 200;
const serviceListeners = new Set<(services: ServiceSummary[]) => void>();

let rendererWebContents: WebContents | null = null;

function setRendererWebContents(webContents: WebContents): void {
  rendererWebContents = webContents;
}

function appendLog(service: PythonService, stream: 'stdout' | 'stderr', line: string): void {
  const entry: LogEntry = {
    serviceId: service.id,
    serviceName: service.name,
    stream,
    line,
    timestamp: new Date().toISOString(),
  };

  const buffer = logBuffers.get(service.id) ?? [];
  buffer.push(entry);
  if (buffer.length > LOG_BUFFER_LIMIT) {
    buffer.splice(0, buffer.length - LOG_BUFFER_LIMIT);
  }
  logBuffers.set(service.id, buffer);

  if (rendererWebContents && !rendererWebContents.isDestroyed()) {
    rendererWebContents.send('logs/append', entry);
  }
}

function attachServiceLogging(service: PythonService): void {
  if (service.process.stdout) {
    const stdoutReader = createInterface({ input: service.process.stdout });
    stdoutReader.on('line', (line) => appendLog(service, 'stdout', line));
    service.process.stdout.on('close', () => stdoutReader.close());
  }

  if (service.process.stderr) {
    const stderrReader = createInterface({ input: service.process.stderr });
    stderrReader.on('line', (line) => appendLog(service, 'stderr', line));
    service.process.stderr.on('close', () => stderrReader.close());
  }
}

function notifyServicesChanged(): void {
  const summaries = listServices();
  serviceListeners.forEach((listener) => {
    try {
      listener(summaries);
    } catch (error) {
      console.error('Failed to notify service listener', error);
    }
  });
}

export function getRecentLogs(): LogEntry[] {
  return Array.from(logBuffers.values())
    .flat()
    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
}

/**
 * Run a one-shot Python command and collect its output.
 *
 * @param args Arguments to pass to the Python interpreter, e.g. `['-m', 'onepiece', 'doctor']`.
 * @returns A promise resolving with the exit code, stdout, and stderr collected from the process.
 */
export function runCommand(
  args: string[],
): Promise<{ code: number; stdout: string; stderr: string }> {
  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';

    let child: ChildProcess;

    try {
      child = spawn(pythonPath, args, { env: process.env });
    } catch (error) {
      console.error('Failed to spawn Python command:', error);
      reject(error);
      return;
    }

    child.stdout?.on('data', (data: Buffer | string) => {
      stdout += data.toString();
    });

    child.stderr?.on('data', (data: Buffer | string) => {
      stderr += data.toString();
    });

    child.on('error', (error) => {
      console.error('Python command process error:', error);
      reject(error);
    });

    child.on('close', (code) => {
      resolve({
        code: code ?? -1,
        stdout,
        stderr,
      });
    });
  });
}

export function runOnepieceInfo(additionalArgs: string[] = []): Promise<{ code: number; stdout: string; stderr: string }> {
  const args = ['-m', 'onepiece', 'info', ...additionalArgs];
  return runCommand(args);
}

export function runOnepieceProfile(
  additionalArgs: string[] = [],
): Promise<{ code: number; stdout: string; stderr: string }> {
  const args = ['-m', 'onepiece', 'profile', ...additionalArgs];
  return runCommand(args);
}

/**
 * Start a long-running Python service process.
 *
 * @param name A descriptive name of the service being started.
 * @param args Arguments to pass to the Python interpreter for the service process.
 * @returns A promise that resolves with the generated service id.
 */
export function startService(name: string, args: string[]): Promise<{ id: string }> {
  return new Promise((resolve, reject) => {
    let child: ChildProcess;
    try {
      child = spawn(pythonPath, args, { env: process.env });
    } catch (error) {
      console.error(`Failed to start Python service '${name}':`, error);
      reject(error);
      return;
    }

    const id = randomUUID();
    const service: PythonService = { id, name, process: child };
    services.set(id, service);

    attachServiceLogging(service);

    notifyServicesChanged();

    child.on('error', (error) => {
      console.error(`Python service '${name}' encountered an error:`, error);
      services.delete(id);
      logBuffers.delete(id);
      notifyServicesChanged();
    });

    child.on('exit', () => {
      services.delete(id);
      logBuffers.delete(id);
      notifyServicesChanged();
    });

    resolve({ id });
  });
}

/**
 * Stop a running Python service by id.
 *
 * @param id Identifier of the service to stop.
 */
export function stopService(id: string): Promise<void> {
  const service = services.get(id);
  if (!service) {
    return Promise.reject(new Error(`Service with id '${id}' not found`));
  }

  return new Promise((resolve, reject) => {
    const onExit = () => {
      services.delete(id);
      resolve();
    };

    service.process.once('exit', onExit);

    const killed = service.process.kill();
    if (!killed) {
      service.process.removeListener('exit', onExit);
      reject(new Error(`Failed to stop service with id '${id}'`));
    }
  });
}

/**
 * List currently running Python services.
 *
 * @returns A summary of running services with their ids, names, and PIDs.
 */
export function listServices(): ServiceSummary[] {
  return Array.from(services.values()).map((service) => ({
    id: service.id,
    name: service.name,
    pid: service.process.pid ?? -1,
  }));
}

export function onServicesChanged(
  listener: (services: ServiceSummary[]) => void,
): () => void {
  serviceListeners.add(listener);
  return () => {
    serviceListeners.delete(listener);
  };
}

/**
 * Register IPC handlers to expose Python management functions to the renderer.
 *
 * @param ipcMain Electron IpcMain instance used to register handlers.
 * @param browserWindow Primary BrowserWindow used for sending log events.
 */
export function registerPythonIpcHandlers(ipcMain: IpcMain, browserWindow: BrowserWindow): void {
  setRendererWebContents(browserWindow.webContents);

  ipcMain.handle(
    'python/run-command',
    async (_event, payload: string[] | { args: string[] }) =>
      runCommand(Array.isArray(payload) ? payload : payload.args),
  );

  ipcMain.handle(
    'python/start-service',
    async (
      _event,
      payload: { name: string; args: string[] } | string,
      args?: string[],
    ) => {
      if (typeof payload === 'string') {
        return startService(payload, args ?? []);
      }
      return startService(payload.name, payload.args);
    },
  );

  ipcMain.handle(
    'python/stop-service',
    async (_event, payload: string | { id: string }) => stopService(typeof payload === 'string' ? payload : payload.id),
  );

  ipcMain.handle('python/list-services', async () => listServices());

  ipcMain.handle('logs/recent', async () => getRecentLogs());

  ipcMain.handle(
    'onepiece/info',
    async (_event, payload: { checkIntegrations?: boolean } = {}) => {
      const args = payload.checkIntegrations ? ['--check-integrations'] : [];
      return runOnepieceInfo(args);
    },
  );

  ipcMain.handle(
    'onepiece/profile',
    async (_event, payload: { showSources?: boolean } = {}) => {
      const args = payload.showSources ? ['--show-sources'] : [];
      return runOnepieceProfile(args);
    },
  );

  ipcMain.handle(
    'onepiece/dcc-open-shot',
    async (_event, payload: { scenePath: string; dcc?: string }) => {
      if (!payload?.scenePath) {
        throw new Error('Scene path is required to open a shot.');
      }

      const args = ['-m', 'onepiece', 'dcc', 'open-shot', '--scene', payload.scenePath];

      if (payload.dcc) {
        args.push('--dcc', payload.dcc);
      }

      return runCommand(args);
    },
  );
}
