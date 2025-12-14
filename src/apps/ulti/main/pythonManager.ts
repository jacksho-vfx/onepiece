import { ChildProcess, spawn } from 'child_process';
import { randomUUID } from 'crypto';
import type { App, BrowserWindow, IpcMain, WebContents } from 'electron';
import { createTask } from './taskManager';
import { ensureDefaultConfig, type DesktopConfig } from './configManager';
import { primePythonPath, resolvePythonPath } from './pythonPathResolver';
import { detectEnvironment, formatEnvironmentDiagnostics } from './envDetection';

/**
 * Represents a running Python service process.
 */
interface PythonService {
  id: string;
  name: string;
  process: ChildProcess;
  key?: string;
  persistent?: boolean;
  taskId?: string;
}

export interface ServiceSummary {
  id: string;
  key?: string;
  name: string;
  pid: number;
  persistent?: boolean;
}

export interface LogEntry {
  serviceId: string;
  serviceKey?: string;
  serviceName: string;
  stream: 'stdout' | 'stderr';
  line: string;
  timestamp: string;
  persistent?: boolean;
}

export interface ServiceProfile {
  key: string;
  name: string;
  description?: string;
  args: string[];
  persistent?: boolean;
}

interface ServiceLaunchPayload {
  key?: string;
  name: string;
  args: string[];
  persistent?: boolean;
}

/**
 * Track running Python services keyed by their generated id.
 */
const services = new Map<string, PythonService>();
const logBuffers = new Map<string, LogEntry[]>();
const LOG_BUFFER_LIMIT = 200;
const serviceListeners = new Set<(services: ServiceSummary[]) => void>();
let serviceProfiles: ServiceProfile[] = [];
let serviceEnabledState: Record<string, boolean> = {};

let rendererWebContents: WebContents | null = null;

function setRendererWebContents(webContents: WebContents): void {
  rendererWebContents = webContents;
}

function appendLog(service: PythonService, stream: 'stdout' | 'stderr', line: string): void {
  const entry: LogEntry = {
    serviceId: service.id,
    serviceKey: service.key,
    serviceName: service.name,
    stream,
    line,
    timestamp: new Date().toISOString(),
    persistent: Boolean(service.persistent),
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

function appendLogChunk(service: PythonService, stream: 'stdout' | 'stderr', chunk: string): void {
  chunk
    .split(/\r?\n/)
    .filter((line) => line.length > 0)
    .forEach((line) => appendLog(service, stream, line));
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

function setServiceConfig(services: DesktopConfig['services'] | undefined): void {
  serviceProfiles = services?.profiles ?? [];
  serviceEnabledState = services?.enabled ?? {};
}

function getServiceByKey(key: string): PythonService | undefined {
  for (const service of services.values()) {
    if (service.key === key) {
      return service;
    }
  }
  return undefined;
}

async function startEnabledPersistentServices(): Promise<void> {
  for (const profile of serviceProfiles) {
    const isEnabled = serviceEnabledState[profile.key] ?? Boolean(profile.persistent);
    if (!profile.persistent || !isEnabled) {
      continue;
    }

    const alreadyRunning = getServiceByKey(profile.key);
    if (alreadyRunning) {
      continue;
    }

    try {
      await startService({ ...profile, key: profile.key });
    } catch (error) {
      console.error(`Failed to auto-start service '${profile.name}'`, error);
    }
  }
}

export async function primeServicesFromConfig(app: App): Promise<void> {
  if (typeof app?.getPath !== 'function') {
    console.warn('Skipping service priming: app.getPath is not available');
    return;
  }

  const config = await ensureDefaultConfig(app);
  setServiceConfig(config.services);
  await startEnabledPersistentServices();
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
 * @param options Optional overrides (e.g. timeoutMs) used to control process handling.
 * @returns A promise resolving with the exit code, stdout, and stderr collected from the process.
 */
export interface RunCommandOptions {
  timeoutMs?: number;
}

/**
 * Default timeout (in milliseconds) applied to IPC runCommand calls. Provide `timeoutMs`
 * in the IPC payload to override this for long-running operations.
 */
export const DEFAULT_RUN_COMMAND_TIMEOUT_MS = 30000;

function withDefaultTimeout(options?: RunCommandOptions): RunCommandOptions {
  return { timeoutMs: options?.timeoutMs ?? DEFAULT_RUN_COMMAND_TIMEOUT_MS };
}

export async function runCommand(
  args: string[],
  options: RunCommandOptions = {},
): Promise<{ code: number; stdout: string; stderr: string }> {
  const pythonPath = await resolvePythonPath();

  return new Promise((resolve, reject) => {
    let stdout = '';
    let stderr = '';

    let child: ChildProcess;
    let timeoutId: NodeJS.Timeout | null = null;
    let finished = false;

    const clearTimeoutIfNeeded = (): void => {
      if (!timeoutId) return;
      clearTimeout(timeoutId);
      timeoutId = null;
    };

    const settle = <T>(handler: (value: T) => void, payload: T): void => {
      if (finished) {
        return;
      }

      finished = true;
      clearTimeoutIfNeeded();
      handler(payload);
    };

    try {
      child = spawn(pythonPath, args, { env: process.env });
    } catch (error) {
      console.error('Failed to spawn Python command:', error);
      settle(reject, error as Error);
      return;
    }

    if (options.timeoutMs && options.timeoutMs > 0) {
      timeoutId = setTimeout(() => {
        const killed = child.kill();
        if (!killed) {
          child.kill('SIGKILL');
        }

        const timeoutMessage = `Python command timed out after ${options.timeoutMs}ms: ${args.join(' ')}`;
        settle(reject, new Error(timeoutMessage));
      }, options.timeoutMs);
    }

    child.stdout?.on('data', (data: Buffer | string) => {
      if (finished) return;
      stdout += data.toString();
    });

    child.stderr?.on('data', (data: Buffer | string) => {
      if (finished) return;
      stderr += data.toString();
    });

    child.on('error', (error) => {
      console.error('Python command process error:', error);
      settle(reject, error);
    });

    child.on('close', (code) => {
      settle(resolve, {
        code: code ?? -1,
        stdout,
        stderr,
      });
    });
  });
}

export function runOnepieceInfo(
  additionalArgs: string[] = [],
  options?: RunCommandOptions,
): Promise<{ code: number; stdout: string; stderr: string }> {
  const args = ['-m', 'onepiece', 'info', ...additionalArgs];
  return runCommand(args, options);
}

export function runOnepieceProfile(
  additionalArgs: string[] = [],
  options?: RunCommandOptions,
): Promise<{ code: number; stdout: string; stderr: string }> {
  const args = ['-m', 'onepiece', 'profile', ...additionalArgs];
  return runCommand(args, options);
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
export async function runOnepieceEnvSummary(
  options?: RunCommandOptions,
): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const result = await runOnepieceInfo(['--format', 'json'], options);
  return mapCommandResult(result);
}

/**
 * Run the profile summary command exposed by the discovered OnePiece CLI.
 */
export async function runOnepieceProfileSummary(
  options?: RunCommandOptions,
): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const result = await runOnepieceProfile([], options);
  return mapCommandResult(result);
}

/**
 * Run the OnePiece doctor command via the info helper.
 */
export async function runOnepieceDoctor(
  options?: RunCommandOptions,
): Promise<{ exitCode: number; stdout: string; stderr: string }> {
  const result = await runOnepieceInfo(['--doctor'], options);
  return mapCommandResult(result);
}

/**
 * Start a long-running Python service process.
 *
 * @param name A descriptive name of the service being started.
 * @param args Arguments to pass to the Python interpreter for the service process.
 * @returns A promise that resolves with the generated service id.
 */
export async function startService(payload: ServiceLaunchPayload): Promise<{ id: string }> {
  const existing = payload.key ? getServiceByKey(payload.key) : undefined;
  if (existing) {
    return { id: existing.id };
  }

  const id = payload.key ?? randomUUID();
  let serviceRef: PythonService | null = null;

  const taskId = await createTask(`Service: ${payload.name}`, payload.args, {
    taskId: id,
    onSpawn: (child) => {
      serviceRef = {
        id,
        key: payload.key,
        name: payload.name,
        persistent: payload.persistent,
        process: child,
        taskId,
      };

      services.set(id, serviceRef);
      notifyServicesChanged();

      child.on('error', (error) => {
        console.error(`Python service '${payload.name}' encountered an error:`, error);
        services.delete(id);
        logBuffers.delete(id);
        notifyServicesChanged();
      });

      child.on('exit', () => {
        services.delete(id);
        logBuffers.delete(id);
        notifyServicesChanged();
      });
    },
    onStdout: (chunk) => {
      if (serviceRef) {
        appendLogChunk(serviceRef, 'stdout', chunk);
      }
    },
    onStderr: (chunk) => {
      if (serviceRef) {
        appendLogChunk(serviceRef, 'stderr', chunk);
      }
    },
  });

  if (!serviceRef) {
    throw new Error(`Failed to start service '${payload.name}'`);
  }

  return { id: taskId };
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
    key: service.key,
    name: service.name,
    pid: service.process.pid ?? -1,
    persistent: Boolean(service.persistent),
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

export async function applyServiceConfig(services: DesktopConfig['services']): Promise<void> {
  setServiceConfig(services);
  await startEnabledPersistentServices();
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
  void primeServicesFromConfig(app);
  setRendererWebContents(browserWindow.webContents);

  ipcMain.handle(
    'python/run-command',
    async (
      _event,
      payload: string[] | { args: string[]; timeoutMs?: number },
    ) => {
      const args = Array.isArray(payload) ? payload : payload.args;
      const timeoutMs = Array.isArray(payload) ? undefined : payload.timeoutMs;

      return runCommand(args, withDefaultTimeout({ timeoutMs }));
    },
  );

  ipcMain.handle(
    'python/run-doctor',
    async (_event, payload: { timeoutMs?: number } = {}) => {
      const [doctorResult, envDiagnostics] = await Promise.all([
        runOnepieceDoctor(withDefaultTimeout(payload)),
        detectEnvironment(app),
      ]);

      const environmentBlock = `\n\n# Pipeline Doctor environment\n${formatEnvironmentDiagnostics(envDiagnostics)}`;

      return {
        ...doctorResult,
        stdout: `${doctorResult.stdout}${environmentBlock}`,
        envDiagnostics,
      };
    },
  );

  ipcMain.handle(
    'python/start-service',
    async (
      _event,
      payload: ServiceLaunchPayload | string,
      args?: string[],
    ) => {
      if (typeof payload === 'string') {
        return startService({ name: payload, args: args ?? [] });
      }
      return startService(payload);
    },
  );

  ipcMain.handle(
    'python/stop-service',
    async (_event, payload: string | { id: string }) => stopService(typeof payload === 'string' ? payload : payload.id),
  );

  ipcMain.handle('python/list-services', async () => listServices());

  ipcMain.handle('python/apply-service-config', async (_event, services: DesktopConfig['services']) => {
    await applyServiceConfig(services);
    return listServices();
  });

  ipcMain.handle('logs/recent', async () => getRecentLogs());

  ipcMain.handle(
    'onepiece/info',
    async (
      _event,
      payload: { checkIntegrations?: boolean; timeoutMs?: number } = {},
    ) => {
      const args = payload.checkIntegrations ? ['--check-integrations'] : [];
      return runOnepieceInfo(args, withDefaultTimeout(payload));
    },
  );

  ipcMain.handle(
    'onepiece/profile',
    async (
      _event,
      payload: { showSources?: boolean; timeoutMs?: number } = {},
    ) => {
      const args = payload.showSources ? ['--show-sources'] : [];
      return runOnepieceProfile(args, withDefaultTimeout(payload));
    },
  );

  ipcMain.handle('onepiece/env-summary', async () => runOnepieceEnvSummary(withDefaultTimeout()));

  ipcMain.handle(
    'onepiece/profile-summary',
    async () => runOnepieceProfileSummary(withDefaultTimeout()),
  );

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
        timeoutMs?: number;
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
        const result = await runCommand(args, withDefaultTimeout(payload));
        return mapCommandResult(result);
      }

      const label = `Unreal import: ${asset} (${project})`;
      return { taskId: await createTask(label, args) };
    },
  );

  ipcMain.handle(
    'onepiece/animation-debug',
    async (_event, payload: { sceneName: string; timeoutMs?: number }) => {
      const sceneName = payload?.sceneName?.trim();

      if (!sceneName) {
        throw new Error('Scene name is required to debug animation.');
      }

      const args = ['-m', 'onepiece', 'dcc', 'animation', 'debug-animation', '--scene-name', sceneName];

      return runCommand(args, withDefaultTimeout(payload));
    },
  );

  ipcMain.handle(
    'onepiece/animation-cleanup',
    async (
      _event,
      payload: {
        sceneName: string;
        keepUnusedReferences?: boolean;
        keepNamespaces?: boolean;
        timeoutMs?: number;
      },
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

      return runCommand(args, withDefaultTimeout(payload));
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
        timeoutMs?: number;
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

      return runCommand(args, withDefaultTimeout(payload));
    },
  );

  ipcMain.handle(
    'onepiece/dcc-open-shot',
    async (_event, payload: { scenePath: string; dcc?: string; timeoutMs?: number }) => {
      if (!payload?.scenePath) {
        throw new Error('Scene path is required to open a shot.');
      }

      const args = ['-m', 'onepiece', 'dcc', 'open-shot', '--scene', payload.scenePath];

      if (payload.dcc) {
        args.push('--dcc', payload.dcc);
      }

      return runCommand(args, withDefaultTimeout(payload));
    },
  );
}
