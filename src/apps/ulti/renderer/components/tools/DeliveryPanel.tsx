import React, { useEffect, useMemo, useState } from 'react';
import { Button, Card, SectionHeader, StatusBadge, Tabs, TextInput, useToast } from '../ui';
import { useTheme } from '../../styles/ThemeContext';

type CommandResult = { code: number; stdout: string; stderr: string };

type TaskStatus = 'pending' | 'running' | 'succeeded' | 'failed';

type Task = {
  id: string;
  label: string;
  status: TaskStatus;
  exitCode?: number;
  createdAt: string;
  startedAt?: string;
  finishedAt?: string;
};

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
      on?: (channel: string, listener: (event: unknown, payload: Task[] | Task) => void) => () => void;
    };
  }
}

type ShotgridResult = {
  running: boolean;
  result: CommandResult | null;
  error?: string | null;
};

type PlaylistTaskState = {
  taskId?: string;
  error?: string | null;
  isStarting: boolean;
};

type DeliveryTaskState = {
  taskId?: string;
  error?: string | null;
  isStarting: boolean;
};

function DeliveryPanel(): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();

  const [activeTab, setActiveTab] = useState<'showSetup' | 'packagePlaylist' | 'deliver'>('showSetup');

  const [showSetupForm, setShowSetupForm] = useState({ csvPath: '', project: '', template: '' });
  const [showSetupState, setShowSetupState] = useState<ShotgridResult>({ running: false, result: null });

  const [packageForm, setPackageForm] = useState({
    project: '',
    playlist: '',
    destination: '',
    recipient: 'client',
  });
  const [packageState, setPackageState] = useState<PlaylistTaskState>({ isStarting: false });

  const [deliverForm, setDeliverForm] = useState({
    project: '',
    playlistOrEpisodes: '',
    outputFolder: '',
    context: '',
    archiveName: '',
    manifest: '',
  });
  const [deliverState, setDeliverState] = useState<DeliveryTaskState>({ isStarting: false });

  const [tasks, setTasks] = useState<Task[]>([]);

  useEffect(() => {
    let isMounted = true;

    const loadTasks = async (): Promise<void> => {
      try {
        const initial = await window.electron.invoke<Task[]>('tasks/list');
        if (isMounted) {
          setTasks(initial);
        }
      } catch (error) {
        console.error('Failed to load tasks for ShotGrid panel', error);
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

  const getTask = (id?: string): Task | undefined => tasks.find((task) => task.id === id);

  const formatTaskStatus = (taskId?: string): string => {
    const task = getTask(taskId);
    if (!task) {
      return taskId ? 'Waiting for task status…' : 'Not started';
    }

    switch (task.status) {
      case 'pending':
        return 'Pending';
      case 'running':
        return 'Running';
      case 'succeeded':
        return 'Succeeded';
      case 'failed':
        return task.exitCode != null ? `Failed (code ${task.exitCode})` : 'Failed';
      default:
        return task.status;
    }
  };

  const formatOutput = (result: CommandResult | null): string => {
    if (!result) {
      return '';
    }
    return [result.stdout, result.stderr].filter(Boolean).join('\n');
  };

  const handleRunShowSetup = async (): Promise<void> => {
    if (!showSetupForm.csvPath.trim() || !showSetupForm.project.trim()) {
      setShowSetupState({ running: false, result: null, error: 'CSV path and project are required.' });
      return;
    }

    setShowSetupState({ running: true, result: null, error: null });

    const payload = {
      csvPath: showSetupForm.csvPath.trim(),
      project: showSetupForm.project.trim(),
      template: showSetupForm.template.trim() || undefined,
    };

    try {
      const result = await window.electron.invoke<CommandResult>('onepiece/shotgrid-show-setup', payload);
      setShowSetupState({ running: false, result, error: null });

      if (result.code === 0) {
        showToast({ kind: 'success', message: 'Show seeded' });
      } else {
        showToast({ kind: 'error', message: 'Show setup reported issues' });
      }
    } catch (error) {
      console.error('Failed to run show setup', error);
      setShowSetupState({
        running: false,
        result: null,
        error: 'Unable to start show setup. Check the inputs and try again.',
      });
      showToast({ kind: 'error', message: 'Show setup failed' });
    }
  };

  const handleStartPackagePlaylist = async (): Promise<void> => {
    if (!packageForm.project.trim() || !packageForm.playlist.trim()) {
      setPackageState({ isStarting: false, error: 'Project and playlist are required.' });
      return;
    }

    setPackageState({ isStarting: true, error: null, taskId: packageState.taskId });

    const payload = {
      project: packageForm.project.trim(),
      playlist: packageForm.playlist.trim(),
      destination: packageForm.destination.trim() || undefined,
      recipient: packageForm.recipient.trim() || undefined,
    };

    try {
      const response = await window.electron.invoke<{ taskId: string }>('onepiece/shotgrid-package-playlist', payload);
      setPackageState({ isStarting: false, taskId: response.taskId, error: null });
      showToast({ kind: 'success', message: 'Playlist packaged' });
    } catch (error) {
      console.error('Failed to start playlist packaging', error);
      setPackageState({ isStarting: false, taskId: undefined, error: 'Unable to start the playlist packaging task.' });
      showToast({ kind: 'error', message: 'Playlist packaging failed' });
    }
  };

  const deriveDeliveryOutput = (): string => {
    const destination = deliverForm.outputFolder.trim();
    if (!destination) {
      return '';
    }

    const archiveName = (deliverForm.archiveName || deliverForm.playlistOrEpisodes || deliverForm.project || 'delivery')
      .trim()
      .replace(/\s+/g, '_')
      .toLowerCase();

    const normalizedDestination = destination.endsWith('/') || destination.endsWith('\\')
      ? destination.slice(0, -1)
      : destination;

    return `${normalizedDestination}/${archiveName || 'delivery'}.zip`;
  };

  const handleStartDelivery = async (): Promise<void> => {
    if (!deliverForm.project.trim() || !deliverForm.context.trim() || !deliverForm.outputFolder.trim()) {
      setDeliverState({ isStarting: false, error: 'Project, output folder, and delivery context are required.' });
      return;
    }

    setDeliverState({ isStarting: true, error: null, taskId: deliverState.taskId });

    const episodes = deliverForm.playlistOrEpisodes
      .split(/[,\n]/)
      .map((item) => item.trim())
      .filter(Boolean);

    const payload = {
      project: deliverForm.project.trim(),
      context: deliverForm.context.trim(),
      output: deriveDeliveryOutput(),
      episodes: episodes.length ? episodes : undefined,
      manifest: deliverForm.manifest.trim() || undefined,
    };

    try {
      const response = await window.electron.invoke<{ taskId: string }>('onepiece/shotgrid-deliver', payload);
      setDeliverState({ isStarting: false, error: null, taskId: response.taskId });
      showToast({ kind: 'success', message: 'Delivery created' });
    } catch (error) {
      console.error('Failed to start delivery', error);
      setDeliverState({ isStarting: false, taskId: undefined, error: 'Unable to start the delivery task.' });
      showToast({ kind: 'error', message: 'Delivery failed to start' });
    }
  };

  const renderShowSetupTab = (): JSX.Element => (
    <div style={{ display: 'grid', gap: theme.spacing.md }}>
      <div style={{ display: 'grid', gap: theme.spacing.sm }}>
        <TextInput
          label="CSV manifest path"
          placeholder="/path/to/shots.csv"
          value={showSetupForm.csvPath}
          onChange={(event) => setShowSetupForm((prev) => ({ ...prev, csvPath: event.target.value }))}
          required
        />
        <TextInput
          label="Project name"
          placeholder="Frost Giant"
          value={showSetupForm.project}
          onChange={(event) => setShowSetupForm((prev) => ({ ...prev, project: event.target.value }))}
          required
        />
        <TextInput
          label="Template (optional)"
          placeholder="FG"
          value={showSetupForm.template}
          onChange={(event) => setShowSetupForm((prev) => ({ ...prev, template: event.target.value }))}
        />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
        <Button onClick={() => void handleRunShowSetup()} isLoading={showSetupState.running}>
          Seed ShotGrid show
        </Button>
        {showSetupState.result ? (
          <StatusBadge status={showSetupState.result.code === 0 ? 'success' : 'error'}>
            {showSetupState.result.code === 0 ? 'Completed' : `Exited with code ${showSetupState.result.code}`}
          </StatusBadge>
        ) : null}
      </div>

      {showSetupState.error ? <p className="op-error">{showSetupState.error}</p> : null}

      <div>
        <p className="op-eyebrow">Result log</p>
        {showSetupState.result ? (
          <pre className="op-log-output">{formatOutput(showSetupState.result)}</pre>
        ) : (
          <p className="op-muted">Run the show setup helper to see logs.</p>
        )}
      </div>
    </div>
  );

  const renderPackagePlaylistTab = (): JSX.Element => {
    const taskStatus = formatTaskStatus(packageState.taskId);
    const task = getTask(packageState.taskId);

    return (
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <TextInput
            label="Playlist name or ID"
            placeholder="client_preview_v1"
            value={packageForm.playlist}
            onChange={(event) => setPackageForm((prev) => ({ ...prev, playlist: event.target.value }))}
            required
          />
        <TextInput
          label="Project"
          placeholder="Frost Giant"
          value={packageForm.project}
          onChange={(event) => setPackageForm((prev) => ({ ...prev, project: event.target.value }))}
          required
        />
        <TextInput
          label="Output folder"
          placeholder="/projects/deliveries/playlist_package"
          value={packageForm.destination}
          onChange={(event) => setPackageForm((prev) => ({ ...prev, destination: event.target.value }))}
          description="CLI builds the MediaShuttle-friendly package in this directory."
        />
        <TextInput
          label="Recipient"
          placeholder="client"
          value={packageForm.recipient}
          onChange={(event) => setPackageForm((prev) => ({ ...prev, recipient: event.target.value }))}
          description="Use client or vendor to mirror the CLI flag."
        />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
          <Button onClick={() => void handleStartPackagePlaylist()} isLoading={packageState.isStarting}>
            Package playlist
          </Button>
          <StatusBadge status={task?.status ?? 'pending'}>{taskStatus}</StatusBadge>
        </div>

        {packageState.error ? <p className="op-error">{packageState.error}</p> : null}
      </div>
    );
  };

  const renderDeliveryTab = (): JSX.Element => {
    const taskStatus = formatTaskStatus(deliverState.taskId);
    const task = getTask(deliverState.taskId);
    const outputPath = deriveDeliveryOutput();

    return (
      <div style={{ display: 'grid', gap: theme.spacing.md }}>
        <div style={{ display: 'grid', gap: theme.spacing.sm }}>
          <TextInput
            label="Playlist / Episode filter"
            placeholder="EP01, EP02"
            value={deliverForm.playlistOrEpisodes}
            onChange={(event) => setDeliverForm((prev) => ({ ...prev, playlistOrEpisodes: event.target.value }))}
            description="Optional filter; episodes are passed to the delivery CLI."
          />
          <TextInput
            label="Project"
            placeholder="Frost Giant"
            value={deliverForm.project}
            onChange={(event) => setDeliverForm((prev) => ({ ...prev, project: event.target.value }))}
            required
          />
          <TextInput
            label="Output folder"
            placeholder="/projects/deliveries/client_out"
            value={deliverForm.outputFolder}
            onChange={(event) => setDeliverForm((prev) => ({ ...prev, outputFolder: event.target.value }))}
            required
            description="A ZIP archive will be created inside this folder."
          />
          {outputPath ? (
            <p className="op-muted" style={{ margin: 0 }}>
              Resolved output: <code>{outputPath}</code>
            </p>
          ) : null}
          <TextInput
            label="Archive name (optional)"
            placeholder="client_preview_v001"
            value={deliverForm.archiveName}
            onChange={(event) => setDeliverForm((prev) => ({ ...prev, archiveName: event.target.value }))}
            description="Defaults to playlist filter or project name if left blank."
          />
          <TextInput
            label="Delivery context (S3 bucket)"
            placeholder="vendor_out"
            value={deliverForm.context}
            onChange={(event) => setDeliverForm((prev) => ({ ...prev, context: event.target.value }))}
            required
            description="Used as the --context flag; maps to s3://<context>/<project>."
          />
          <TextInput
            label="Manifest output (optional)"
            placeholder="/projects/deliveries/client_out/manifest"
            value={deliverForm.manifest}
            onChange={(event) => setDeliverForm((prev) => ({ ...prev, manifest: event.target.value }))}
            description="Write manifest.json/csv alongside the archive instead of inside it."
          />
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: theme.spacing.sm }}>
          <Button onClick={() => void handleStartDelivery()} isLoading={deliverState.isStarting}>
            Build delivery package
          </Button>
          <StatusBadge status={task?.status ?? 'pending'}>{taskStatus}</StatusBadge>
        </div>

        {deliverState.error ? <p className="op-error">{deliverState.error}</p> : null}
      </div>
    );
  };

  const tabContent = useMemo(() => {
    switch (activeTab) {
      case 'showSetup':
        return renderShowSetupTab();
      case 'packagePlaylist':
        return renderPackagePlaylistTab();
      case 'deliver':
        return renderDeliveryTab();
      default:
        return null;
    }
  }, [activeTab, showSetupState, packageState, deliverState, showSetupForm, packageForm, deliverForm, tasks]);

  return (
    <Card>
      <div style={{ display: 'grid', gap: theme.spacing.lg }}>
        <SectionHeader
          title="ShotGrid & Delivery"
          subtitle="Seed shows, package playlists, and trigger delivery uploads using the existing CLIs."
        />

        <Tabs
          tabs={[
            { id: 'showSetup', label: 'Show setup' },
            { id: 'packagePlaylist', label: 'Package playlist' },
            { id: 'deliver', label: 'Deliver' },
          ]}
          activeTabId={activeTab}
          onTabChange={(id) => setActiveTab(id as typeof activeTab)}
        />

        <div>{tabContent}</div>
      </div>
    </Card>
  );
}

export default DeliveryPanel;
