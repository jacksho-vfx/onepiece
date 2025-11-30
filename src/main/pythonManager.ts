import { ChildProcess, spawn } from 'child_process';
import { randomUUID } from 'crypto';
import type { IpcMain } from 'electron';

/**
 * Represents a running Python service process.
 */
interface PythonService {
  id: string;
  name: string;
  process: ChildProcess;
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

    child.on('error', (error) => {
      console.error(`Python service '${name}' encountered an error:`, error);
      services.delete(id);
    });

    child.on('exit', () => {
      services.delete(id);
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
export function listServices(): { id: string; name: string; pid: number }[] {
  return Array.from(services.values()).map((service) => ({
    id: service.id,
    name: service.name,
    pid: service.process.pid ?? -1,
  }));
}

/**
 * Register IPC handlers to expose Python management functions to the renderer.
 *
 * @param ipcMain Electron IpcMain instance used to register handlers.
 */
export function registerPythonIpcHandlers(ipcMain: IpcMain): void {
  ipcMain.handle('python/run-command', async (_event, args: string[]) => runCommand(args));
  ipcMain.handle('python/start-service', async (_event, name: string, args: string[]) =>
    startService(name, args),
  );
  ipcMain.handle('python/stop-service', async (_event, id: string) => stopService(id));
  ipcMain.handle('python/list-services', async () => listServices());
}
