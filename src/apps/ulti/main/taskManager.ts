import { spawn, type ChildProcess } from 'child_process';
import { randomUUID } from 'crypto';
import { Notification, type App, type BrowserWindow, type IpcMain, type WebContents } from 'electron';
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

const tasks = new Map<string, Task>();

let rendererWebContents: WebContents | null = null;
let appInstance: App | null = null;

export const TASK_TTL_MS = 1000 * 60 * 60 * 24 * 7;
export const MAX_TASK_HISTORY = 100;

const completedStatuses: TaskStatus[] = ['succeeded', 'failed'];

const isTaskCompleted = (task: Task): boolean => completedStatuses.includes(task.status);

const getSortedTasks = (): Task[] =>
  Array.from(tasks.values()).sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );

function emitTasksUpdated(snapshot?: Task[]): void {
  if (rendererWebContents && !rendererWebContents.isDestroyed()) {
    rendererWebContents.send('tasks/updated', snapshot ?? getTasks());
  }
}

function setRendererWebContents(webContents: WebContents): void {
  rendererWebContents = webContents;
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

async function maybeShowTaskNotification(task: Task, previousStatus: TaskStatus): Promise<void> {
  if (!appInstance) {
    return;
  }

  if ((task.status !== 'succeeded' && task.status !== 'failed') || task.status === previousStatus) {
    return;
  }

  const config = await ensureDefaultConfig(appInstance);
  if (config.enableNotifications === false) {
    return;
  }

  const title = task.status === 'succeeded' ? 'OnePiece task completed' : 'OnePiece task failed';
  const body = `Task "${task.label}" ${task.status}.`;

  const notification = new Notification({ title, body });
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
}

export async function createTask(label: string, args: string[]): Promise<string> {
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
