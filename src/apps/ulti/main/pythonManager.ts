import { ChildProcess, spawn } from 'child_process';
import { randomUUID } from 'crypto';
import type { App, BrowserWindow, IpcMain, WebContents } from 'electron';
import { createInterface } from 'readline';
import { createTask } from './taskManager';
import { primePythonPath, resolvePythonPath } from './pythonPathResolver';

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
export async function runCommand(
  args: string[],
): Promise<{ code: number; stdout: string; stderr: string }> {
  const pythonPath = await resolvePythonPath();

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

function mapCommandResult(result: { code: number; stdout: string; stderr: string }): {
  exitCode: number;
  stdout: string;
  stderr: string;
} {
  return {
    exitCode: result.code,
    stdout: result.stdout,
    stderr: result.stderr,
  };
}

/**
 * Run the environment summary command exposed by the discovered OnePiece CLI.
 */
export async function runOnepieceEnvSummary(): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const result = await runOnepieceInfo(['--format', 'json']);
  return mapCommandResult(result);
}

/**
 * Run the profile summary command exposed by the discovered OnePiece CLI.
 */
export async function runOnepieceProfileSummary(): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const result = await runOnepieceProfile();
  return mapCommandResult(result);
}

/**
 * Start a long-running Python service process.
 *
 * @param name A descriptive name of the service being started.
 * @param args Arguments to pass to the Python interpreter for the service process.
 * @returns A promise that resolves with the generated service id.
 */
export function startService(name: string, args: string[]): Promise<{ id: string }> {
  return new Promise(async (resolve, reject) => {
    const pythonPath = await resolvePythonPath();

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
export function registerPythonIpcHandlers(
  ipcMain: IpcMain,
  browserWindow: BrowserWindow,
  app: App,
): void {
  primePythonPath(app);
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

  ipcMain.handle('onepiece/env-summary', async () => runOnepieceEnvSummary());

  ipcMain.handle('onepiece/profile-summary', async () => runOnepieceProfileSummary());

  ipcMain.handle(
    'onepiece/dcc-import-unreal',
    async (
      _event,
      payload: {
        packagePath: string;
        project: string;
        asset: string;
        dryRun?: boolean;
        extraArgs?: string[];
      },
    ) => {
      const packagePath = payload?.packagePath?.trim();
      const project = payload?.project?.trim();
      const asset = payload?.asset?.trim();

      if (!packagePath || !project || !asset) {
        throw new Error('packagePath, project, and asset are required for Unreal imports.');
      }

      const args = [
        '-m',
        'onepiece',
        'dcc',
        'import-unreal',
        '--package',
        packagePath,
        '--project',
        project,
        '--asset',
        asset,
      ];

      if (payload?.dryRun) {
        args.push('--dry-run');
      }

      if (Array.isArray(payload?.extraArgs) && payload.extraArgs.length > 0) {
        args.push(...payload.extraArgs);
      }

      if (payload?.dryRun) {
        const result = await runCommand(args);
        return mapCommandResult(result);
      }

      const label = `Unreal import: ${asset} (${project})`;
      return { taskId: await createTask(label, args) };
    },
  );

  ipcMain.handle(
    'onepiece/animation-debug',
    async (_event, payload: { sceneName: string }) => {
      const sceneName = payload?.sceneName?.trim();

      if (!sceneName) {
        throw new Error('Scene name is required to debug animation.');
      }

      const args = ['-m', 'onepiece', 'dcc', 'animation', 'debug-animation', '--scene-name', sceneName];

      return runCommand(args);
    },
  );

  ipcMain.handle(
    'onepiece/animation-cleanup',
    async (
      _event,
      payload: { sceneName: string; keepUnusedReferences?: boolean; keepNamespaces?: boolean },
    ) => {
      const sceneName = payload?.sceneName?.trim();

      if (!sceneName) {
        throw new Error('Scene name is required to clean up a scene.');
      }

      const args = ['-m', 'onepiece', 'dcc', 'animation', 'cleanup-scene'];

      args.push('--scene-name', sceneName);

      if (payload.keepUnusedReferences) {
        args.push('--keep-unused-references');
      }

      if (payload.keepNamespaces) {
        args.push('--keep-namespaces');
      }

      return runCommand(args);
    },
  );

  ipcMain.handle(
    'onepiece/animation-playblast',
    async (
      _event,
      payload: {
        project: string;
        sequence?: string | null;
        shot: string;
        artist: string;
        camera: string;
        version: number;
        outputDirectory: string;
        format?: string;
        codec?: string;
        width?: number;
        height?: number;
        frameStart?: number | null;
        frameEnd?: number | null;
        description?: string | null;
        includeAudio?: boolean;
      },
    ) => {
      const {
        project,
        sequence,
        shot,
        artist,
        camera,
        version,
        outputDirectory,
        format,
        codec,
        width,
        height,
        frameStart,
        frameEnd,
        description,
        includeAudio,
      } = payload ?? {};

      if (!project || !shot || !artist || !camera || !outputDirectory) {
        throw new Error('Project, shot, artist, camera, and output directory are required for playblasts.');
      }

      if (frameStart !== undefined || frameEnd !== undefined) {
        if (frameStart == null || frameEnd == null) {
          throw new Error('Both frameStart and frameEnd must be provided together.');
        }
      }

      const args = [
        '-m',
        'onepiece',
        'dcc',
        'animation',
        'playblast',
        '--project',
        project,
        '--shot',
        shot,
        '--artist',
        artist,
        '--camera',
        camera,
        '--version',
        String(version),
        '--output-directory',
        outputDirectory,
      ];

      if (sequence) {
        args.push('--sequence', sequence);
      }

      if (format) {
        args.push('--format', format);
      }

      if (codec) {
        args.push('--codec', codec);
      }

      if (width) {
        args.push('--width', String(width));
      }

      if (height) {
        args.push('--height', String(height));
      }

      if (frameStart != null && frameEnd != null) {
        args.push('--frame-start', String(frameStart), '--frame-end', String(frameEnd));
      }

      if (description) {
        args.push('--description', description);
      }

      if (includeAudio) {
        args.push('--include-audio');
      }

      return runCommand(args);
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
