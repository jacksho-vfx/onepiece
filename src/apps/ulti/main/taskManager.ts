import { spawn, type ChildProcess } from 'child_process';
import { randomUUID } from 'crypto';
import type { App, BrowserWindow, IpcMain, Notification as ElectronNotification, WebContents } from 'electron';
import { ensureDefaultConfig } from './configManager';
import { primePythonPath, resolvePythonPath } from './pythonPathResolver';

export type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

export interface Task {
  id: string;
  label: string;
  command: string[];
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  status: TaskStatus;
  exitCode?: number;
}

export interface TaskOptions {
  onStdout?: (chunk: string) => void;
  onStderr?: (chunk: string) => void;
}

const tasks = new Map<string, Task>();
const completionListeners = new Map<string, Array<(task: Task) => void>>();

let electronModule: typeof import('electron') | null = null;

if (process.versions.electron) {
  // eslint-disable-next-line @typescript-eslint/no-var-requires
  electronModule = require('electron') as typeof import('electron');
}

let rendererWebContents: WebContents | null = null;
let appInstance: App | null = null;

export const TASK_TTL_MS = 1000 * 60 * 60 * 24 * 7;
export const MAX_TASK_HISTORY = 100;

const completedStatuses: TaskStatus[] = ['succeeded', 'failed'];

const MAX_CAPTURED_OUTPUT_BYTES = 1024 * 1024; // 1MB

const isTaskCompleted = (task: Task): boolean => completedStatuses.includes(task.status);

const getNotificationCtor = (): typeof ElectronNotification | undefined => electronModule?.Notification;

const getSortedTasks = (): Task[] =>
  Array.from(tasks.values()).sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );

function emitTasksUpdated(snapshot?: Task[]): void {
  if (rendererWebContents && !rendererWebContents.isDestroyed()) {
    rendererWebContents.send('tasks/updated', snapshot ?? getTasks());
  }
}

function resolveCompletionListeners(task: Task): void {
  const listeners = completionListeners.get(task.id);

  if (!listeners || listeners.length === 0) {
    return;
  }

  for (const listener of listeners) {
    listener(task);
  }

  completionListeners.delete(task.id);
}

function setRendererWebContents(webContents: WebContents): void {
  rendererWebContents = webContents;
}

function createStreamCapture(
  stream: NodeJS.ReadableStream | null | undefined,
  taskId: string,
  label: string,
): {
  getPreview: () => string;
  isTruncated: () => boolean;
} {
  let captured = '';
  let truncated = false;

  if (stream) {
    stream.on('data', (data: Buffer | string) => {
      const chunk = data.toString();
      const remaining = Math.max(0, MAX_CAPTURED_OUTPUT_BYTES - captured.length);

      if (remaining > 0) {
        captured += chunk.slice(0, remaining);
      }

      if (chunk.length > remaining) {
        truncated = true;
      }
    });

    stream.on('error', (error) => {
      console.error(`Error reading ${label} for task '${taskId}'`, error);
    });
  }

  return {
    getPreview: () => captured,
    isTruncated: () => truncated,
  };
}

export function enforceTaskRetention(): { mutated: boolean; snapshot: Task[] } {
  const now = Date.now();
  let mutated = false;

  for (const [id, task] of tasks) {
    if (!isTaskCompleted(task)) {
      continue;
    }

    const finishedAt = task.finishedAt ?? task.createdAt;
    const finishedTime = new Date(finishedAt).getTime();

    if (Number.isFinite(finishedTime) && now - finishedTime > TASK_TTL_MS) {
      tasks.delete(id);
      mutated = true;
    }
  }

  const allTasks = getSortedTasks();
  const overflow = Math.max(0, allTasks.length - MAX_TASK_HISTORY);

  if (overflow > 0) {
    const completedOldestFirst = allTasks
      .filter((task) => isTaskCompleted(task))
      .sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime());

    let remaining = overflow;

    for (const task of completedOldestFirst) {
      if (remaining <= 0) {
        break;
      }

      if (tasks.delete(task.id)) {
        remaining -= 1;
        mutated = true;
      }
    }
  }

  return { mutated, snapshot: getSortedTasks() };
}

export function clearCompletedTasks(): Task[] {
  let mutated = false;

  for (const [id, task] of tasks) {
    if (isTaskCompleted(task)) {
      tasks.delete(id);
      mutated = true;
    }
  }

  const snapshot = getSortedTasks();

  if (mutated) {
    emitTasksUpdated(snapshot);
  }

  return snapshot;
}

export function replaceTasksForTesting(taskList: Task[]): void {
  tasks.clear();

  for (const task of taskList) {
    tasks.set(task.id, task);
  }
}

export function waitForTaskCompletion(taskId: string): Promise<Task> {
  const existing = tasks.get(taskId);

  if (existing && isTaskCompleted(existing)) {
    return Promise.resolve(existing);
  }

  return new Promise((resolve) => {
    const listeners = completionListeners.get(taskId) ?? [];
    listeners.push(resolve);
    completionListeners.set(taskId, listeners);
  });
}

async function maybeShowTaskNotification(task: Task, previousStatus: TaskStatus): Promise<void> {
  if (!appInstance) {
    return;
  }

  if ((task.status !== 'succeeded' && task.status !== 'failed') || task.status === previousStatus) {
    return;
  }

  const NotificationCtor = getNotificationCtor();

  if (!NotificationCtor) {
    return;
  }

  const config = await ensureDefaultConfig(appInstance);
  if (config.enableNotifications === false) {
    return;
  }

  const title = task.status === 'succeeded' ? 'OnePiece task completed' : 'OnePiece task failed';
  const body = `Task "${task.label}" ${task.status}.`;

  const notification = new NotificationCtor({ title, body });
  notification.show();
}

async function updateTask(id: string, updates: Partial<Task>): Promise<void> {
  const existing = tasks.get(id);
  if (!existing) {
    return;
  }

  const previousStatus = existing.status;
  const nextTask = { ...existing, ...updates };
  tasks.set(id, nextTask);

  const { snapshot } = enforceTaskRetention();
  emitTasksUpdated(snapshot);

  await maybeShowTaskNotification(nextTask, previousStatus);

  if (!isTaskCompleted(existing) && isTaskCompleted(nextTask)) {
    resolveCompletionListeners(nextTask);
  }
}

export async function createTask(
  label: string,
  args: string[],
  options?: TaskOptions,
): Promise<string> {
  const id = randomUUID();
  const createdAt = new Date().toISOString();

  const task: Task = {
    id,
    label,
    command: args,
    createdAt,
    status: 'pending',
  };

  tasks.set(id, task);

  const { snapshot } = enforceTaskRetention();
  emitTasksUpdated(snapshot);

  let child: ChildProcess;

  const pythonPath = await resolvePythonPath();

  try {
    child = spawn(pythonPath, args, { env: process.env });
  } catch (error) {
    console.error('Failed to create task process', error);
    void updateTask(id, {
      status: 'failed',
      finishedAt: new Date().toISOString(),
      exitCode: -1,
    });
    return id;
  }

  const stdoutCapture = createStreamCapture(child.stdout, id, 'stdout');
  const stderrCapture = createStreamCapture(child.stderr, id, 'stderr');

  if (options?.onStdout && child.stdout) {
    child.stdout.on('data', (data: Buffer | string) => {
      options.onStdout?.(data.toString());
    });
  }

  if (options?.onStderr && child.stderr) {
    child.stderr.on('data', (data: Buffer | string) => {
      options.onStderr?.(data.toString());
    });
  }

  void updateTask(id, {
    status: 'running',
    startedAt: new Date().toISOString(),
  });

  child.on('error', (error) => {
    console.error(`Task '${label}' encountered an error`, error);
    void updateTask(id, {
      status: 'failed',
      finishedAt: new Date().toISOString(),
      exitCode: -1,
    });
  });

  child.on('close', (code) => {
    const logPreview = (
      name: 'stdout' | 'stderr',
      capture: ReturnType<typeof createStreamCapture>,
    ): void => {
      const preview = capture.getPreview();

      if (preview) {
        const truncatedSuffix = capture.isTruncated() ? ' (truncated)' : '';
        console.debug(`Task '${label}' ${name}${truncatedSuffix}: ${preview}`);
      }
    };

    logPreview('stdout', stdoutCapture);
    logPreview('stderr', stderrCapture);

    void updateTask(id, {
      status: code === 0 ? 'succeeded' : 'failed',
      finishedAt: new Date().toISOString(),
      exitCode: code ?? -1,
    });
  });

  return id;
}

export function getTasks(): Task[] {
  return enforceTaskRetention().snapshot;
}

export function getTask(id: string): Task | undefined {
  return tasks.get(id);
}

export function registerTaskIpcHandlers(
  ipcMain: IpcMain,
  browserWindow: BrowserWindow,
  app: App,
): void {
  setRendererWebContents(browserWindow.webContents);
  appInstance = app;
  primePythonPath(app);

  ipcMain.handle('tasks/create', async (_event, payload: { label: string; args: string[] }) =>
    createTask(payload.label, payload.args),
  );

  ipcMain.handle('tasks/clear-completed', async () => clearCompletedTasks());

  ipcMain.handle('tasks/list', async () => getTasks());

  ipcMain.handle('tasks/get', async (_event, id: string) => getTask(id));
}
