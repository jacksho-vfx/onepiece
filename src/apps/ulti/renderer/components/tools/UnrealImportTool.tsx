import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, SectionHeader, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

interface UnrealImportToolProps {
  project?: { name: string; path: string } | null;
}

type DryRunResult = {
  stdout: string;
  stderr: string;
  exitCode: number;
};

type ParsedImportTask = {
  source?: string;
  destination_path?: string;
  destination_name?: string | null;
  task_settings?: Record<string, unknown>;
  factory_class?: string | null;
  factory_settings?: Record<string, unknown>;
};

type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

type Task = {
  id: string;
  label: string;
  status: TaskStatus;
  exitCode?: number;
};

const parseExtraArgs = (raw: string): string[] => {
  const tokens = raw.match(/(?:[^\s"]+|"[^"]*")+/g) ?? [];
  return tokens.map((token) => token.replace(/^"|"$/g, ''));
};

function UnrealImportTool({ project }: UnrealImportToolProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const directoryInputRef = useRef<HTMLInputElement | null>(null);
  const notifiedTaskIds = useRef<Set<string>>(new Set());
  const lastRunContext = useRef<{ packagePath: string; project: string; asset: string } | null>(null);

  const [packagePath, setPackagePath] = useState('');
  const [projectCode, setProjectCode] = useState('');
  const [assetName, setAssetName] = useState('');
  const [dryRunOnly, setDryRunOnly] = useState(false);
  const [extraArgs, setExtraArgs] = useState('');

  const [isPreviewing, setIsPreviewing] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [preview, setPreview] = useState<DryRunResult | null>(null);
  const [parsedTasks, setParsedTasks] = useState<ParsedImportTask[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stderrTail, setStderrTail] = useState<string>('');
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    if (!project || projectCode) {
      return;
    }
    setProjectCode(project.name);
  }, [project, projectCode]);

  useEffect(() => {
    if (!activeTaskId) {
      return;
    }

    let isMounted = true;
    const loadTasks = async (): Promise<void> => {
      try {
        const response = await window.electron.invoke<Task[]>('tasks/list');
        if (isMounted) {
          setTasks(response);
        }
      } catch (err) {
        console.error('Failed to load tasks for Unreal import tool', err);
      }
    };

    void loadTasks();

    return () => {
      isMounted = false;
    };
  }, [activeTaskId]);

  useEffect(() => {
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
      if (unsubscribe) {
        unsubscribe();
      }
    };
  }, []);

  useEffect(() => {
    if (!activeTaskId) {
      return;
    }

    const task = tasks.find((item) => item.id === activeTaskId);
    if (!task || notifiedTaskIds.current.has(task.id)) {
      return;
    }

    if (task.status === 'succeeded') {
      const context = lastRunContext.current;
      showToast({
        kind: 'success',
        message:
          context
            ? `Imported package ${context.packagePath} into Unreal project ${context.project} as ${context.asset}`
            : 'Unreal import completed successfully',
      });
      notifiedTaskIds.current.add(task.id);
    }

    if (task.status === 'failed') {
      showToast({
        kind: 'error',
        message: task.exitCode != null ? `Unreal import failed (code ${task.exitCode})` : 'Unreal import failed',
      });
      notifiedTaskIds.current.add(task.id);
    }
  }, [activeTaskId, showToast, tasks]);

  const isFormValid = useMemo(
    () => Boolean(packagePath.trim() && projectCode.trim() && assetName.trim()),
    [assetName, packagePath, projectCode],
  );

  const parsedPreviewTasks = useMemo(() => {
    if (!preview) {
      return null;
    }

    try {
      const parsed = JSON.parse(preview.stdout || '');
      const tasksArray = Array.isArray(parsed)
        ? parsed
        : parsed && typeof parsed === 'object' && Array.isArray((parsed as { tasks?: unknown }).tasks)
          ? (parsed as { tasks?: unknown }).tasks
          : null;

      if (!tasksArray) {
        return null;
      }

      const normalized = tasksArray
        .map((task) => {
          if (!task || typeof task !== 'object') {
            return null;
          }

          const candidate = task as Record<string, unknown>;
          return {
            source: typeof candidate.source === 'string' ? candidate.source : undefined,
            destination_path:
              typeof candidate.destination_path === 'string' ? candidate.destination_path : undefined,
            destination_name:
              typeof candidate.destination_name === 'string' || candidate.destination_name === null
                ? candidate.destination_name
                : undefined,
            task_settings:
              candidate.task_settings && typeof candidate.task_settings === 'object'
                ? (candidate.task_settings as Record<string, unknown>)
                : undefined,
            factory_class:
              typeof candidate.factory_class === 'string' || candidate.factory_class === null
                ? candidate.factory_class
                : undefined,
            factory_settings:
              candidate.factory_settings && typeof candidate.factory_settings === 'object'
                ? (candidate.factory_settings as Record<string, unknown>)
                : undefined,
          } satisfies ParsedImportTask;
        })
        .filter(Boolean) as ParsedImportTask[];

      return normalized.length > 0 ? normalized : null;
    } catch (err) {
      console.warn('Failed to parse Unreal import dry-run output as JSON', err);
      return null;
    }
  }, [preview]);

  useEffect(() => {
    setParsedTasks(parsedPreviewTasks);
  }, [parsedPreviewTasks]);

  const browseForPackage = (): void => {
    directoryInputRef.current?.click();
  };

  const handleDirectoryPicked = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    const path = (file as unknown as { path?: string })?.path ?? '';
    if (path) {
      setPackagePath(path);
    }

    event.target.value = '';
  };

  const formatTail = (text: string): string => {
    if (!text) {
      return '';
    }
    const lines = text.split('\n').filter(Boolean);
    return lines.slice(Math.max(0, lines.length - 6)).join('\n');
  };

  const handlePreview = async (): Promise<void> => {
    setIsPreviewing(true);
    setError(null);
    setStderrTail('');
    setPreview(null);
    setParsedTasks(null);

    try {
      const extra = parseExtraArgs(extraArgs);
      const result = await window.electron.invoke<DryRunResult>('onepiece/dcc-import-unreal', {
        packagePath: packagePath.trim(),
        project: projectCode.trim(),
        asset: assetName.trim(),
        dryRun: true,
        extraArgs: extra.length > 0 ? extra : undefined,
      });

      setPreview(result);
      if (result.exitCode !== 0) {
        setError(`Dry-run exited with code ${result.exitCode}.`);
        setStderrTail(formatTail(result.stderr || result.stdout));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Dry-run failed.');
    } finally {
      setIsPreviewing(false);
    }
  };

  const handleRunImport = async (): Promise<void> => {
    if (dryRunOnly) {
      showToast({ kind: 'info', message: 'Dry-run only is enabled. Run a preview instead.' });
      return;
    }

    setIsRunning(true);
    setError(null);
    setStderrTail('');

    try {
      const extra = parseExtraArgs(extraArgs);
      const response = await window.electron.invoke<{ taskId: string }>('onepiece/dcc-import-unreal', {
        packagePath: packagePath.trim(),
        project: projectCode.trim(),
        asset: assetName.trim(),
        dryRun: false,
        extraArgs: extra.length > 0 ? extra : undefined,
      });

      const taskId = response?.taskId;
      if (taskId) {
        lastRunContext.current = {
          packagePath: packagePath.trim(),
          project: projectCode.trim(),
          asset: assetName.trim(),
        };
        setActiveTaskId(taskId);
      }

      showToast({ kind: 'info', message: 'Unreal import started – see Tasks for progress' });
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start Unreal import.');
    } finally {
      setIsRunning(false);
    }
  };

  const renderTaskSummary = (task: ParsedImportTask, index: number): JSX.Element => {
    return (
      <div
        key={`${task.destination_path}-${index}`}
        style={{
          border: `1px solid ${theme.colors.border}`,
          borderRadius: theme.radii.md,
          padding: theme.spacing.sm,
          background: theme.colors.surfaceAlt,
        }}
      >
        <div style={{ fontWeight: theme.typography.fontWeightSemiBold }}>{task.destination_path ?? 'Unreal asset'}</div>
        <div className="op-muted" style={{ fontSize: theme.typography.fontSizeSm }}>
          {task.source ? `Source: ${task.source}` : 'Source not reported'}
        </div>
        {task.destination_name ? (
          <div className="op-muted" style={{ fontSize: theme.typography.fontSizeSm }}>
            Destination name: {task.destination_name}
          </div>
        ) : null}
        {task.factory_class ? (
          <div className="op-muted" style={{ fontSize: theme.typography.fontSizeSm }}>
            Factory: {task.factory_class}
          </div>
        ) : null}
      </div>
    );
  };

  return (
    <Card>
      <SectionHeader
        title="Unreal Import"
        subtitle="Rehydrate published packages into Unreal, with dry-run previews."
      />

      {project ? (
        <p className="op-muted" style={{ marginTop: 0 }}>
          Current project: <strong>{project.name}</strong> ({project.path})
        </p>
      ) : null}

      <div
        style={{
          display: 'grid',
          gap: theme.spacing.md,
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          alignItems: 'end',
        }}
      >
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <TextInput
            label="Package folder"
            placeholder="/path/to/published/package"
            value={packagePath}
            onChange={(event) => setPackagePath(event.target.value)}
            required
          />
          <div style={{ display: 'flex', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <Button variant="secondary" onClick={browseForPackage} style={{ justifyContent: 'center' }}>
              Browse…
            </Button>
            <input
              ref={directoryInputRef}
              type="file"
              style={{ display: 'none' }}
              webkitdirectory="true"
              directory="true"
              onChange={handleDirectoryPicked}
            />
          </div>
        </div>

        <TextInput
          label="Unreal project code"
          placeholder="Matches the --project CLI value"
          value={projectCode}
          onChange={(event) => setProjectCode(event.target.value)}
          required
        />

        <TextInput
          label="Asset name"
          placeholder="Matches the --asset CLI value"
          value={assetName}
          onChange={(event) => setAssetName(event.target.value)}
          required
        />

        <TextInput
          label="Extra CLI args (optional)"
          placeholder="--some-flag value"
          value={extraArgs}
          onChange={(event) => setExtraArgs(event.target.value)}
        />
      </div>

      <label style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm, marginTop: theme.spacing.sm }}>
        <input
          type="checkbox"
          checked={dryRunOnly}
          onChange={(event) => setDryRunOnly(event.target.checked)}
        />
        <span>Dry-run only (don’t import, just print tasks)</span>
      </label>

      <div style={{ display: 'flex', gap: theme.spacing.sm, flexWrap: 'wrap', marginTop: theme.spacing.sm }}>
        <Button
          onClick={() => void handlePreview()}
          isLoading={isPreviewing}
          disabled={!isFormValid || isRunning}
          variant="secondary"
        >
          Preview tasks
        </Button>
        <Button onClick={() => void handleRunImport()} isLoading={isRunning} disabled={!isFormValid || isPreviewing || dryRunOnly}>
          Run import into Unreal
        </Button>
      </div>

      {error ? (
        <div
          style={{
            marginTop: theme.spacing.sm,
            border: `1px solid ${theme.colors.danger}`,
            borderRadius: theme.radii.md,
            padding: theme.spacing.sm,
            background: theme.colors.surface,
          }}
        >
          <p style={{ margin: 0, color: theme.colors.danger }}>{error}</p>
          {stderrTail ? (
            <pre
              style={{
                margin: `${theme.spacing.xs} 0 0`,
                padding: theme.spacing.sm,
                background: theme.colors.surfaceAlt,
                borderRadius: theme.radii.sm,
                border: `1px solid ${theme.colors.border}`,
                maxHeight: 160,
                overflow: 'auto',
              }}
            >
              {stderrTail}
            </pre>
          ) : null}
        </div>
      ) : null}

      {preview ? (
        <div style={{ marginTop: theme.spacing.md, display: 'grid', gap: theme.spacing.sm }}>
          {parsedTasks ? (
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <div style={{ fontWeight: theme.typography.fontWeightSemiBold }}>
                Preview generated {parsedTasks.length} task{parsedTasks.length === 1 ? '' : 's'}.
              </div>
              <div
                style={{
                  display: 'grid',
                  gap: theme.spacing.sm,
                  gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                }}
              >
                {parsedTasks.slice(0, 3).map((task, index) => renderTaskSummary(task, index))}
              </div>
            </div>
          ) : (
            <div style={{ fontWeight: theme.typography.fontWeightSemiBold }}>Dry-run output</div>
          )}

          <pre
            style={{
              margin: 0,
              padding: theme.spacing.sm,
              background: theme.colors.surfaceAlt,
              borderRadius: theme.radii.sm,
              border: `1px solid ${theme.colors.border}`,
              maxHeight: 260,
              overflow: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {preview.stdout || preview.stderr || 'No output captured.'}
          </pre>
        </div>
      ) : null}
    </Card>
  );
}

export default UnrealImportTool;
