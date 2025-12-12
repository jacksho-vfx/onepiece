import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';
import {
  MAX_TASK_HISTORY,
  TASK_TTL_MS,
  Task,
  clearCompletedTasks,
  createTask,
  enforceTaskRetention,
  getTask,
  getTasks,
  replaceTasksForTesting,
  waitForTaskCompletion,
} from '../taskManager';
import * as pythonPathResolver from '../pythonPathResolver';

vi.mock('electron', () => ({
  Notification: vi.fn().mockImplementation(() => ({ show: vi.fn() })),
}));

beforeEach(() => {
  replaceTasksForTesting([]);
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const waitForTaskWithTimeout = async (taskId: string, timeoutMs = 5000): Promise<Task> =>
  Promise.race([
    waitForTaskCompletion(taskId),
    new Promise<never>((_resolve, reject) =>
      setTimeout(() => reject(new Error('Timed out waiting for task completion')), timeoutMs),
    ),
  ]);

describe('taskManager retention', () => {
  it('removes completed tasks beyond the TTL', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2024-01-08T00:00:00Z'));

    const staleFinishedAt = new Date(Date.now() - TASK_TTL_MS - 1).toISOString();
    const freshFinishedAt = new Date(Date.now() - TASK_TTL_MS + 1000).toISOString();

    const tasks: Task[] = [
      {
        id: 'stale',
        label: 'Old task',
        command: [],
        createdAt: staleFinishedAt,
        finishedAt: staleFinishedAt,
        status: 'succeeded',
      },
      {
        id: 'recent',
        label: 'Recent task',
        command: [],
        createdAt: freshFinishedAt,
        finishedAt: freshFinishedAt,
        status: 'succeeded',
      },
    ];

    replaceTasksForTesting(tasks);

    const { snapshot } = enforceTaskRetention();
    const remainingIds = snapshot.map((task) => task.id);

    expect(remainingIds).toContain('recent');
    expect(remainingIds).not.toContain('stale');
  });

  it('limits stored tasks to the max history by removing the oldest completed entries', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2024-01-06T00:00:00Z'));

    const tasks: Task[] = Array.from({ length: MAX_TASK_HISTORY + 5 }, (_value, index) => {
      const createdAt = new Date(Date.UTC(2024, 0, 1, index)).toISOString();
      return {
        id: `task-${index}`,
        label: `Task ${index}`,
        command: [],
        createdAt,
        finishedAt: createdAt,
        status: 'succeeded',
      } satisfies Task;
    });

    replaceTasksForTesting(tasks);

    const { snapshot } = enforceTaskRetention();
    const remainingIds = snapshot.map((task) => task.id);

    expect(snapshot).toHaveLength(MAX_TASK_HISTORY);
    expect(remainingIds).not.toContain('task-0');
    expect(remainingIds).not.toContain('task-1');
    expect(remainingIds).not.toContain('task-2');
    expect(remainingIds).not.toContain('task-3');
    expect(remainingIds).not.toContain('task-4');
    expect(remainingIds).toContain(`task-${MAX_TASK_HISTORY + 4}`);
  });

  it('clears completed tasks while retaining active ones', () => {
    const tasks: Task[] = [
      {
        id: 'running',
        label: 'Running task',
        command: [],
        createdAt: new Date().toISOString(),
        status: 'running',
      },
      {
        id: 'done',
        label: 'Completed task',
        command: [],
        createdAt: new Date().toISOString(),
        finishedAt: new Date().toISOString(),
        status: 'failed',
      },
    ];

    replaceTasksForTesting(tasks);

    const updated = clearCompletedTasks();

    expect(updated).toHaveLength(1);
    expect(updated[0]?.id).toBe('running');
    expect(getTasks().map((task) => task.id)).toEqual(['running']);
  });
});

describe('createTask output handling', () => {
  it('completes tasks that produce verbose output', async () => {
    const noisyScript = `
const chunk = 'spam'.repeat(1000);
for (let i = 0; i < 500; i += 1) {
  console.log(chunk);
  console.error('err' + i);
}
`;

    vi.spyOn(pythonPathResolver, 'resolvePythonPath').mockResolvedValue(process.execPath);

    const taskId = await createTask('chatty task', ['-e', noisyScript]);
    const task = await waitForTaskWithTimeout(taskId, 10000);

    expect(task.status).toBe('succeeded');
    expect(task.exitCode).toBe(0);
  }, 15000);

  it('streams task output to provided handlers while awaiting completion', async () => {
    const stdoutChunks: string[] = [];
    const stderrChunks: string[] = [];
    const script = "console.log('hello from stdout'); console.error('oops from stderr');";

    vi.spyOn(pythonPathResolver, 'resolvePythonPath').mockResolvedValue(process.execPath);

    const taskId = await createTask('streamed task', ['-e', script], {
      onStdout: (chunk) => stdoutChunks.push(chunk),
      onStderr: (chunk) => stderrChunks.push(chunk),
    });

    const task = await waitForTaskWithTimeout(taskId);

    expect(task.status).toBe('succeeded');
    expect(stdoutChunks.join('')).toContain('hello from stdout');
    expect(stderrChunks.join('')).toContain('oops from stderr');
  });
});
