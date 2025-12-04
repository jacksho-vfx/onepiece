import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge } from './ui';
import { useTheme } from '../styles/ThemeContext';

type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

type Task = {
  id: string;
  label: string;
  command: string[];
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
  status: TaskStatus;
  exitCode?: number;
};

const statusLabelMap: Record<TaskStatus, string> = {
  pending: 'Pending',
  running: 'Running',
  succeeded: 'Success',
  failed: 'Failed',
};

const formatDate = (value?: string): string => {
  if (!value) {
    return '—';
  }

  return new Date(value).toLocaleString();
};

const formatDuration = (task: Task): string => {
  if (!task.startedAt) {
    return '—';
  }

  const start = new Date(task.startedAt);
  const end = new Date(task.finishedAt ?? Date.now());
  const totalSeconds = Math.max(0, Math.floor((end.getTime() - start.getTime()) / 1000));

  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;

  const parts = [];
  if (hours) {
    parts.push(`${hours}h`);
  }
  if (minutes || hours) {
    parts.push(`${minutes}m`);
  }
  parts.push(`${seconds}s`);

  return parts.join(' ');
};

const getBasename = (filePath: string): string => filePath.trim().split(/[\\/]/).pop() || filePath;

const parseRenderTask = (task: Task): { scene?: string; frames?: string; farm?: string } | null => {
  const args = task.command;
  const isRenderSubmit = args.includes('render') && args.includes('submit');
  if (!isRenderSubmit) {
    return null;
  }

  const getArgValue = (flag: string): string | undefined => {
    const index = args.indexOf(flag);
    if (index !== -1 && index + 1 < args.length) {
      return args[index + 1];
    }
    return undefined;
  };

  return {
    scene: getArgValue('--scene'),
    frames: getArgValue('--frames'),
    farm: getArgValue('--farm'),
  };
};

function TaskList(): JSX.Element {
  const theme = useTheme();
  const [tasks, setTasks] = useState<Task[]>([]);
  const [statusFilter, setStatusFilter] = useState<'all' | TaskStatus>('all');
  const [renderDashboardUrl, setRenderDashboardUrl] = useState<string | null>(null);
  const [renderDashboardError, setRenderDashboardError] = useState<string | null>(null);
  const hasCompletedTasks = useMemo(
    () => tasks.some((task) => task.status === 'succeeded' || task.status === 'failed'),
    [tasks],
  );
  const openRenderDashboard = (): void => {
    if (!renderDashboardUrl) {
      setRenderDashboardError('Render dashboard URL is not configured.');
      return;
    }

    void window.electron.invoke('open-url', { url: renderDashboardUrl });
  };

  useEffect(() => {
    let isMounted = true;

    const resolveRenderDashboard = async (): Promise<void> => {
      try {
        const resolvedUrl = await window.electron.invoke<string | null>('render/dashboard-url');
        if (!isMounted) {
          return;
        }

        if (resolvedUrl) {
          setRenderDashboardUrl(resolvedUrl);
          setRenderDashboardError(null);
        } else {
          setRenderDashboardUrl(null);
          setRenderDashboardError('Render dashboard URL is not available.');
        }
      } catch (error) {
        console.error('Failed to resolve render dashboard URL', error);
        if (isMounted) {
          setRenderDashboardUrl(null);
          setRenderDashboardError('Render dashboard URL is not available.');
        }
      }
    };

    const loadTasks = async (): Promise<void> => {
      try {
        const initial = await window.electron.invoke<Task[]>('tasks/list');
        if (isMounted) {
          setTasks(initial);
        }
      } catch (error) {
        console.error('Failed to load tasks', error);
      }
    };

    void resolveRenderDashboard();
    void loadTasks();

    const unsubscribe = window.electron.on?.('tasks/updated', (_event, payload: Task[] | Task) => {
      if (Array.isArray(payload)) {
        setTasks(payload);
        return;
      }

      if (payload) {
        setTasks((prev) => {
          const next = new Map(prev.map((task) => [task.id, task]));
          next.set(payload.id, payload);
          return Array.from(next.values());
        });
      }
    });

    return () => {
      isMounted = false;
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, []);

  const visibleTasks = useMemo(() => {
    const filtered = tasks.filter((task) =>
      statusFilter === 'all' ? true : task.status === statusFilter,
    );

    return filtered.sort(
      (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime(),
    );
  }, [statusFilter, tasks]);

  const handleClearCompleted = async (): Promise<void> => {
    try {
      const updated = await window.electron.invoke<Task[]>('tasks/clear-completed');
      setTasks(updated);
    } catch (error) {
      console.error('Failed to clear completed tasks', error);
    }
  };

  return (
    <div style={{ display: 'grid', gap: theme.spacing.lg }}>
      <SectionHeader
        title="Background tasks"
        subtitle="Track long-running CLI invocations started from the desktop."
      />

      <Card>
        <p style={{ margin: 0, color: theme.colors.textMuted }}>
          You will receive a desktop notification when tasks finish. Make sure notifications are
          enabled for this app in your OS settings.
        </p>
      </Card>

      <Card>
        <div
          style={{
            display: 'flex',
            flexWrap: 'wrap',
            gap: theme.spacing.md,
            justifyContent: 'space-between',
            alignItems: 'flex-end',
          }}
        >
          <div style={{ display: 'flex', gap: theme.spacing.md, flexWrap: 'wrap' }}>
            <label style={{ display: 'grid', gap: '0.35rem' }}>
              <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Status</span>
              <select
                value={statusFilter}
                onChange={(event) => setStatusFilter(event.target.value as 'all' | TaskStatus)}
                style={{
                  padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                  borderRadius: theme.radii.md,
                  border: `1px solid ${theme.colors.border}`,
                  background: theme.colors.surfaceAlt,
                  color: theme.colors.text,
                  minWidth: '180px',
                }}
              >
                <option value="all">All</option>
                <option value="pending">Pending</option>
                <option value="running">Running</option>
                <option value="succeeded">Succeeded</option>
                <option value="failed">Failed</option>
              </select>
            </label>
          </div>

          <Button variant="secondary" onClick={handleClearCompleted} disabled={!hasCompletedTasks}>
            Clear completed
          </Button>
        </div>
      </Card>

      <Card title="Tasks">
        {visibleTasks.length === 0 ? (
          <p style={{ margin: 0, color: theme.colors.textMuted }}>No tasks to display.</p>
        ) : (
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))',
              gap: theme.spacing.sm,
              width: '100%',
            }}
          >
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
                gap: theme.spacing.sm,
                padding: `${theme.spacing.xs} ${theme.spacing.sm}`,
                fontWeight: theme.typography.fontWeightMedium,
                color: theme.colors.textMuted,
              }}
            >
              <span>Label</span>
              <span>Status</span>
              <span>Started</span>
              <span>Finished</span>
              <span>Duration</span>
            </div>

            {visibleTasks.map((task) => (
              (() => {
                const renderInfo = parseRenderTask(task);
                const displayLabel = renderInfo
                  ? `Render submit – ${renderInfo.scene ? getBasename(renderInfo.scene) : 'scene'} (${
                      renderInfo.frames || 'default frames'
                    })`
                  : task.label;

                return (
                  <div
                    key={task.id}
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '2fr 1fr 1fr 1fr 1fr',
                      gap: theme.spacing.sm,
                      padding: `${theme.spacing.sm} ${theme.spacing.sm}`,
                      borderRadius: theme.radii.sm,
                      border: `1px solid ${theme.colors.border}`,
                      background: theme.colors.surfaceAlt,
                      alignItems: 'center',
                    }}
                  >
                    <div style={{ display: 'grid', gap: '0.25rem' }}>
                      <strong>{displayLabel}</strong>
                      {renderInfo ? (
                        <div
                          style={{
                            display: 'flex',
                            flexWrap: 'wrap',
                            gap: theme.spacing.sm,
                            alignItems: 'center',
                            color: theme.colors.textMuted,
                          }}
                        >
                          <span>Scene: {renderInfo.scene ? getBasename(renderInfo.scene) : 'Unknown'}</span>
                          <span>Frames: {renderInfo.frames ?? 'Default range'}</span>
                          <span>Farm: {renderInfo.farm ?? 'default'}</span>
                          <Button
                            variant="secondary"
                            onClick={openRenderDashboard}
                            disabled={!renderDashboardUrl}
                          >
                            Open render dashboard
                          </Button>
                          {renderDashboardError ? (
                            <span style={{ color: theme.colors.danger }}>{renderDashboardError}</span>
                          ) : null}
                        </div>
                      ) : null}
                      <code style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
                        {task.command.join(' ')}
                      </code>
                    </div>
                    <StatusBadge status={statusLabelMap[task.status]}>
                      {statusLabelMap[task.status]}
                    </StatusBadge>
                    <span>{formatDate(task.startedAt ?? task.createdAt)}</span>
                    <span>{formatDate(task.finishedAt)}</span>
                    <span>{formatDuration(task)}</span>
                  </div>
                );
              })()
            ))}
          </div>
        )}
      </Card>
    </div>
  );
}

export default TaskList;
