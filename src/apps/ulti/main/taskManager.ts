import { spawn, type ChildProcess } from 'child_process';
import { randomUUID } from 'crypto';
import { Notification, type App, type BrowserWindow, type IpcMain, type WebContents } from 'electron';
import { ensureDefaultConfig } from './configManager';

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

const pythonPath = process.env.ONEPIECE_PYTHON_PATH || 'python';

const tasks = new Map<string, Task>();

let rendererWebContents: WebContents | null = null;
let appInstance: App | null = null;

function emitTasksUpdated(): void {
  if (rendererWebContents && !rendererWebContents.isDestroyed()) {
    rendererWebContents.send('tasks/updated', getTasks());
  }
}

function setRendererWebContents(webContents: WebContents): void {
  rendererWebContents = webContents;
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
  emitTasksUpdated();

  await maybeShowTaskNotification(nextTask, previousStatus);
}

export function createTask(label: string, args: string[]): string {
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
  emitTasksUpdated();

  let child: ChildProcess;

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
  return Array.from(tasks.values()).sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
  );
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

  ipcMain.handle('tasks/create', async (_event, payload: { label: string; args: string[] }) =>
    createTask(payload.label, payload.args),
  );

  ipcMain.handle('tasks/list', async () => getTasks());

  ipcMain.handle('tasks/get', async (_event, id: string) => getTask(id));
}
