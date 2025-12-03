import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

type AwsSyncDirection = 'download' | 'upload';

type AwsSyncPreset = {
  id: string;
  name: string;
  direction: AwsSyncDirection;
  localPath: string;
  remote: string;
};

type AwsSyncPresetInput = AwsSyncPreset & {
  bucketUrl?: string;
  direction: AwsSyncDirection | 'from' | 'to';
};

type AwsConfig = {
  defaultBucket?: string;
};

type DesktopConfig = {
  aws?: AwsConfig;
  awsSyncPresets?: AwsSyncPresetInput[];
};

type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

type Task = {
  id: string;
  label: string;
  status: TaskStatus;
  createdAt: string;
  finishedAt?: string;
};

const normalizePresets = (presets: AwsSyncPresetInput[] | undefined): AwsSyncPreset[] => {
  return (presets ?? []).map((preset) => {
    const normalizedDirection: AwsSyncDirection =
      preset.direction === 'from'
        ? 'download'
        : preset.direction === 'to'
          ? 'upload'
          : preset.direction;

    return {
      id: preset.id,
      name: preset.name,
      direction: normalizedDirection,
      localPath: preset.localPath,
      remote: preset.remote ?? (preset as AwsSyncPresetInput).bucketUrl ?? '',
    } satisfies AwsSyncPreset;
  });
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
      on?: (channel: string, listener: (event: unknown, payload: Task[] | Task) => void) => () => void;
    };
  }
}

function AwsSyncTool(): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const directoryInputRef = useRef<HTMLInputElement | null>(null);

  const [direction, setDirection] = useState<AwsSyncDirection>('download');
  const [localPath, setLocalPath] = useState('');
  const [remotePath, setRemotePath] = useState('');
  const [extraArgs, setExtraArgs] = useState('');
  const [presets, setPresets] = useState<AwsSyncPreset[]>([]);
  const [presetName, setPresetName] = useState('');
  const [selectedPresetId, setSelectedPresetId] = useState('');
  const [tasks, setTasks] = useState<Task[]>([]);
  const [isStarting, setIsStarting] = useState(false);
  const [presetError, setPresetError] = useState<string | null>(null);

  useEffect(() => {
    let isMounted = true;

    const loadConfig = async (): Promise<void> => {
      try {
        const config = await window.electron.invoke<DesktopConfig>('config/get');
        if (!isMounted) return;

        setPresets(normalizePresets(config.awsSyncPresets));

        if (!remotePath && config.aws?.defaultBucket) {
          const normalizedBucket = config.aws.defaultBucket.startsWith('s3://')
            ? config.aws.defaultBucket
            : `s3://${config.aws.defaultBucket}`;
          setRemotePath(normalizedBucket);
        }
      } catch (error) {
        console.error('Failed to load config for AWS sync', error);
      }
    };

    void loadConfig();

    return () => {
      isMounted = false;
    };
  }, []);

  useEffect(() => {
    let isMounted = true;

    const loadTasks = async (): Promise<void> => {
      try {
        const initial = await window.electron.invoke<Task[]>('tasks/list');
        if (isMounted) {
          setTasks(initial);
        }
      } catch (error) {
        console.error('Failed to load tasks for AWS sync tool', error);
      }
    };

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

  useEffect(() => {
    if (!selectedPresetId) {
      return;
    }

    const preset = presets.find((item) => item.id === selectedPresetId);
    if (!preset) {
      return;
    }

    setDirection(preset.direction);
    setLocalPath(preset.localPath);
    setRemotePath(preset.remote);
    setPresetName(preset.name);
  }, [presets, selectedPresetId]);

  const syncTasks = useMemo(() => {
    return tasks
      .filter((task) => task.label?.toLowerCase().startsWith('aws sync'))
      .sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
      .slice(0, 5);
  }, [tasks]);

  const handleBrowseDirectory = (): void => {
    directoryInputRef.current?.click();
  };

  const handleDirectoryPicked = (event: React.ChangeEvent<HTMLInputElement>): void => {
    const file = event.target.files?.[0];
    const path = (file as unknown as { path?: string })?.path ?? '';
    if (path) {
      setLocalPath(path);
    }

    event.target.value = '';
  };

  const formatDate = (value: string): string => {
    const date = new Date(value);
    return date.toLocaleString();
  };

  const formatStatus = (status: TaskStatus): string => {
    switch (status) {
      case 'pending':
        return 'Pending';
      case 'running':
        return 'Running';
      case 'succeeded':
        return 'Succeeded';
      case 'failed':
        return 'Failed';
      default:
        return status;
    }
  };

  const buildExtraArgs = (value: string): string[] => {
    if (!value.trim()) {
      return [];
    }

    return value
      .split(' ')
      .map((part) => part.trim())
      .filter(Boolean);
  };

  const handleStartSync = async (): Promise<void> => {
    if (!localPath.trim() || !remotePath.trim()) {
      setPresetError('Provide both a local path and remote path to start a sync.');
      return;
    }

    setPresetError(null);
    setIsStarting(true);

    try {
      await window.electron.invoke<string>('onepiece/aws-sync', {
        direction,
        localPath: localPath.trim(),
        remote: remotePath.trim(),
        extraArgs: buildExtraArgs(extraArgs),
      });

      showToast({ kind: 'info', message: 'Sync started – see Tasks for progress.' });
    } catch (error) {
      console.error('Failed to start AWS sync', error);
      showToast({
        kind: 'error',
        message: error instanceof Error ? error.message : 'Unable to start sync.',
      });
    } finally {
      setIsStarting(false);
    }
  };

  const handleSavePreset = async (): Promise<void> => {
    if (!presetName.trim()) {
      setPresetError('Give the preset a name before saving.');
      return;
    }

    if (!localPath.trim() || !remotePath.trim()) {
      setPresetError('Provide both a local path and remote path before saving a preset.');
      return;
    }

    setPresetError(null);

    const presetId = selectedPresetId || `aws-sync-${Date.now().toString(16)}`;
    const nextPreset: AwsSyncPreset = {
      id: presetId,
      name: presetName.trim(),
      direction,
      localPath: localPath.trim(),
      remote: remotePath.trim(),
    };

    const nextPresets = [...presets.filter((preset) => preset.id !== presetId), nextPreset];

    try {
      const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', {
        awsSyncPresets: nextPresets,
      });
      setPresets(normalizePresets(updatedConfig.awsSyncPresets));
      setSelectedPresetId(presetId);
      showToast({ kind: 'success', message: 'Preset saved.' });
    } catch (error) {
      console.error('Failed to persist AWS sync preset', error);
      showToast({
        kind: 'error',
        message: 'Could not save preset. Check logs for details.',
      });
    }
  };

  const handleDeletePreset = async (): Promise<void> => {
    if (!selectedPresetId) {
      return;
    }

    const remaining = presets.filter((preset) => preset.id !== selectedPresetId);

    try {
      const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', {
        awsSyncPresets: remaining,
      });
      setPresets(normalizePresets(updatedConfig.awsSyncPresets));
      setSelectedPresetId('');
      setPresetName('');
      showToast({ kind: 'success', message: 'Preset deleted.' });
    } catch (error) {
      console.error('Failed to delete AWS sync preset', error);
      showToast({ kind: 'error', message: 'Could not delete preset.' });
    }
  };

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <SectionHeader
          title="AWS Sync"
          subtitle="Wraps the onepiece aws sync helpers so you can push or pull project data."
        />

        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <label style={{ display: 'grid', gap: '0.35rem' }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Preset</span>
            <select
              value={selectedPresetId}
              onChange={(event) => setSelectedPresetId(event.target.value)}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
              }}
            >
              <option value="">No preset selected</option>
              {presets.map((preset) => (
                <option key={preset.id} value={preset.id}>
                  {preset.name}
                </option>
              ))}
            </select>
            <span style={{ color: theme.colors.textMuted, fontSize: theme.typography.fontSizeSm }}>
              Pick a preset to fill in the sync direction and paths, or enter details and save a new preset.
            </span>
          </label>

          <div style={{ display: 'grid', gap: theme.spacing.sm }}>
            <TextInput
              label="Preset name"
              placeholder="My daily upload"
              value={presetName}
              onChange={(event) => setPresetName(event.target.value)}
            />
            <div style={{ display: 'flex', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
              <Button variant="secondary" onClick={() => void handleSavePreset()}>
                Save preset
              </Button>
              <Button
                variant="secondary"
                onClick={() => void handleDeletePreset()}
                disabled={!selectedPresetId}
              >
                Delete preset
              </Button>
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <label style={{ display: 'grid', gap: '0.35rem' }}>
            <span style={{ fontWeight: theme.typography.fontWeightMedium }}>Direction</span>
            <select
              value={direction}
              onChange={(event) => setDirection(event.target.value as AwsSyncDirection)}
              style={{
                padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                borderRadius: theme.radii.md,
                border: `1px solid ${theme.colors.border}`,
                background: theme.colors.surfaceAlt,
              }}
            >
              <option value="download">Download (S3 → local)</option>
              <option value="upload">Upload (local → S3)</option>
            </select>
          </label>

          <TextInput
            label="Local path"
            placeholder="/path/to/files"
            value={localPath}
            onChange={(event) => setLocalPath(event.target.value)}
            required
          />
          <div style={{ display: 'flex', gap: theme.spacing.sm, flexWrap: 'wrap' }}>
            <Button variant="secondary" onClick={handleBrowseDirectory} style={{ justifyContent: 'center' }}>
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

          <TextInput
            label="Remote path"
            placeholder="s3://bucket/show/path"
            value={remotePath}
            onChange={(event) => setRemotePath(event.target.value)}
            required
          />

          <TextInput
            label="Extra CLI args (optional)"
            placeholder="--delete --acl bucket-owner-full-control"
            value={extraArgs}
            onChange={(event) => setExtraArgs(event.target.value)}
          />
        </div>

        {presetError ? (
          <p style={{ margin: 0, color: theme.colors.danger }}>{presetError}</p>
        ) : null}

        <div style={{ display: 'flex', gap: theme.spacing.sm, alignItems: 'center' }}>
          <Button isLoading={isStarting} onClick={() => void handleStartSync()}>
            Start sync
          </Button>
          <span className="op-muted">Runs as a background task so you can keep working.</span>
        </div>

        <Card title="Recent syncs">
          {syncTasks.length === 0 ? (
            <p style={{ margin: 0, color: theme.colors.textMuted }}>No syncs have run yet.</p>
          ) : (
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              {syncTasks.map((task) => (
                <div
                  key={task.id}
                  style={{
                    display: 'grid',
                    gridTemplateColumns: '1fr auto',
                    gap: theme.spacing.sm,
                    alignItems: 'center',
                    padding: theme.spacing.sm,
                    borderRadius: theme.radii.md,
                    border: `1px solid ${theme.colors.border}`,
                    background: theme.colors.surfaceAlt,
                  }}
                >
                  <div>
                    <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
                      <strong>{task.label}</strong>
                      <StatusBadge status={task.status === 'failed' ? 'Error' : 'Default'}>
                        {formatStatus(task.status)}
                      </StatusBadge>
                    </div>
                    <p style={{ margin: 0, color: theme.colors.textMuted }}>
                      Started {formatDate(task.createdAt)}{' '}
                      {task.finishedAt ? `· Finished ${formatDate(task.finishedAt)}` : ''}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </Card>
  );
}

export default AwsSyncTool;
