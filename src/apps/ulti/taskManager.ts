import { spawn, type ChildProcess } from 'child_process';
import { randomUUID } from 'crypto';
import type { BrowserWindow, IpcMain, WebContents } from 'electron';

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

function emitTasksUpdated(): void {
  if (rendererWebContents && !rendererWebContents.isDestroyed()) {
    rendererWebContents.send('tasks/updated', getTasks());
  }
}

function setRendererWebContents(webContents: WebContents): void {
  rendererWebContents = webContents;
}

function updateTask(id: string, updates: Partial<Task>): void {
  const existing = tasks.get(id);
  if (!existing) {
    return;
  }

  const nextTask = { ...existing, ...updates };
  tasks.set(id, nextTask);
  emitTasksUpdated();
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
    updateTask(id, {
      status: 'failed',
      finishedAt: new Date().toISOString(),
      exitCode: -1,
    });
    return id;
  }

  updateTask(id, {
    status: 'running',
    startedAt: new Date().toISOString(),
  });

  child.on('error', (error) => {
    console.error(`Task '${label}' encountered an error`, error);
    updateTask(id, {
      status: 'failed',
      finishedAt: new Date().toISOString(),
      exitCode: -1,
    });
  });

  child.on('close', (code) => {
    updateTask(id, {
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

export function registerTaskIpcHandlers(ipcMain: IpcMain, browserWindow: BrowserWindow): void {
  setRendererWebContents(browserWindow.webContents);

  ipcMain.handle('tasks/create', async (_event, payload: { label: string; args: string[] }) =>
    createTask(payload.label, payload.args),
  );

  ipcMain.handle('tasks/list', async () => getTasks());

  ipcMain.handle('tasks/get', async (_event, id: string) => getTask(id));
}
