import React, { useEffect, useMemo, useState } from 'react';
import ProjectOverview from './ProjectOverview';
import { Button, Card, Modal, SectionHeader, StatusBadge, Tabs, TextInput, useToast } from './ui';
import VendorIngestWizard from './workflows/VendorIngestWizard';
import DccPublishWizard from './workflows/DccPublishWizard';
import DeliveryWizard from './workflows/DeliveryWizard';
import { useTheme } from '../styles/ThemeContext';
import { useHelpContext } from './HelpContext';

interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  currentProject?: string;
  recentProjects?: { name: string; path: string; lastOpenedAt: string }[];
  quickActionPresets?: {
    [projectName: string]: {
      vendorIngest?: { sourcePath?: string };
      dccPublish?: { dccType?: string; lastScenePath?: string };
      renderSubmit?: { profileName?: string; lastFrameRange?: string };
      clientDelivery?: { playlistName?: string; targetPath?: string };
    };
  };
  dccs?: {
    maya?: { enabled: boolean; executablePath?: string };
    blender?: { enabled: boolean; executablePath?: string };
    unreal?: { enabled: boolean; executablePath?: string };
  };
}

type HomeScreenProps = {
  config?: DesktopConfig;
  onViewLogs?: () => void;
  onViewTasks?: () => void;
  currentProject?: { name: string; path: string };
};

interface ServiceSummary {
  id: string;
  name: string;
  pid: number;
}

type ServiceKey = 'trafalgar' | 'perona' | 'uta' | 'tester';

interface ServiceDefinition {
  key: ServiceKey;
  name: string;
  description: string;
  args: string[];
}

interface HealthCheckState {
  running: boolean;
  exitCode: number | null;
  stdout: string;
  stderr: string;
  error?: string;
}

type QuickActionKey = 'vendorIngest' | 'dccPublish' | 'submitRender' | 'packageDelivery';

interface QuickActionForms {
  vendorIngest: {
    source: string;
    project: string;
  };
  dccPublish: {
    dccType: '' | 'maya' | 'blender' | 'unreal';
    scenePath: string;
  };
  submitRender: {
    profileName: string;
    frameRange: string;
  };
  packageDelivery: {
    playlist: string;
    target: string;
  };
}

interface ActionStatus {
  state: 'idle' | 'running' | 'success' | 'error';
  stdout: string;
  stderr: string;
  error?: string;
}

interface HealthCheckError {
  title: string;
  message: string;
  suggestedAction?: string;
}

declare global {
  interface Window {
    electron: {
      invoke: <T = unknown>(channel: string, payload?: unknown) => Promise<T>;
    };
  }
}

const SERVICE_DEFINITIONS: ServiceDefinition[] = [
  {
    key: 'trafalgar',
    name: 'Trafalgar',
    description: 'Asset management and pipeline orchestration.',
    args: ['-m', 'apps.trafalgar'],
  },
  {
    key: 'perona',
    name: 'Perona',
    description: 'Perona dashboard web service.',
    args: ['-m', 'apps.perona'],
  },
  {
    key: 'uta',
    name: 'Uta Control Center',
    description: 'Monitoring and operations control center.',
    args: ['-m', 'apps.uta'],
  },
  {
    key: 'tester',
    name: 'Tester Demo Stack',
    description: 'Demo stack for validation and testing.',
    args: ['-m', 'apps.tester'],
  },
];

const UTA_PORT = 8080;

const QUICK_ACTIONS: { key: QuickActionKey; label: string; description: string }[] = [
  {
    key: 'vendorIngest',
    label: 'Run Vendor Ingest',
    description: 'Ingest vendor assets into your project.',
  },
  {
    key: 'dccPublish',
    label: 'Run DCC Publish',
    description: 'Publish a scene from an enabled DCC application.',
  },
  {
    key: 'submitRender',
    label: 'Submit Render',
    description: 'Submit a render profile with an optional frame range.',
  },
  {
    key: 'packageDelivery',
    label: 'Package Client Delivery',
    description: 'Bundle a playlist for client delivery.',
  },
];

function formatDoctorOutput(
  stdout: string,
  stderr: string,
  exitCode: number | null = null,
): { isOk: boolean; summary: string } {
  const isOk = exitCode === 0;
  const trimmedError = stderr.trim();
  const summary = isOk
    ? 'All checks passed'
    : trimmedError
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
        .slice(0, 1)
        .join('') || 'Health check reported issues';

  return { isOk, summary: summary || 'All checks passed' };
}

function HomeScreen({ config: initialConfig, onViewLogs, onViewTasks, currentProject }: HomeScreenProps): JSX.Element {
  const theme = useTheme();
  const { showToast } = useToast();
  const [config, setConfig] = useState<DesktopConfig | null>(initialConfig ?? null);
  const [services, setServices] = useState<ServiceSummary[]>([]);
  const [serviceError, setServiceError] = useState<string | null>(null);
  const [healthCheck, setHealthCheck] = useState<HealthCheckState>({
    running: false,
    exitCode: null,
    stdout: '',
    stderr: '',
  });
  const [error, setError] = useState<HealthCheckError | null>(null);
  const [serviceActions, setServiceActions] = useState<Record<ServiceKey, 'starting' | 'stopping' | null>>(() =>
    SERVICE_DEFINITIONS.reduce(
      (acc, definition) => ({
        ...acc,
        [definition.key]: null,
      }),
      {} as Record<ServiceKey, 'starting' | 'stopping' | null>,
    ),
  );
  const [quickActionForms, setQuickActionForms] = useState<QuickActionForms>({
    vendorIngest: { source: '', project: '' },
    dccPublish: { dccType: '', scenePath: '' },
    submitRender: { profileName: '', frameRange: '' },
    packageDelivery: { playlist: '', target: '' },
  });
  const [activeQuickAction, setActiveQuickAction] = useState<QuickActionKey | null>(null);
  const [showVendorIngestWizard, setShowVendorIngestWizard] = useState(false);
  const [showDccPublishWizard, setShowDccPublishWizard] = useState(false);
  const [showDeliveryWizard, setShowDeliveryWizard] = useState(false);
  const [actionStatus, setActionStatus] = useState<ActionStatus>({ state: 'idle', stdout: '', stderr: '' });
  const [activeTab, setActiveTab] = useState<'overview' | 'services' | 'quickActions'>('overview');
  useHelpContext(activeTab === 'overview' ? 'home.overview' : null);

  const fetchConfig = async (): Promise<void> => {
    try {
      const loadedConfig = await window.electron.invoke<DesktopConfig>('config/get');
      setConfig(loadedConfig);
    } catch (error) {
      console.error('Failed to load desktop config', error);
    }
  };

  const fetchServices = async (): Promise<void> => {
    try {
      const summaries = await window.electron.invoke<ServiceSummary[]>('python/list-services');
      setServices(summaries);
      setServiceError(null);
    } catch (error) {
      console.error('Failed to list services', error);
      setServiceError('Unable to retrieve service status.');
    }
  };

  useEffect(() => {
    if (!initialConfig) {
      void fetchConfig();
    }
    void fetchServices();

    const interval = setInterval(() => {
      void fetchServices();
    }, 5000);

    return () => clearInterval(interval);
  }, [initialConfig]);

  useEffect(() => {
    if (initialConfig) {
      setConfig(initialConfig);
    }
  }, [initialConfig]);

  useEffect(() => {
    if (!currentProject) {
      return;
    }

    setQuickActionForms((prev) => ({
      ...prev,
      vendorIngest: {
        ...prev.vendorIngest,
        project: prev.vendorIngest.project || currentProject.name,
      },
    }));
  }, [currentProject]);

  const runningServicesByName = useMemo(() => {
    const map = new Map<string, ServiceSummary>();
    services.forEach((service) => {
      map.set(service.name, service);
    });
    return map;
  }, [services]);

  const availableDccs = useMemo(() => {
    if (!config?.dccs) {
      return [] as QuickActionForms['dccPublish']['dccType'][];
    }

    return (['maya', 'blender', 'unreal'] as const).filter((dcc) => config.dccs?.[dcc]?.enabled);
  }, [config]);

  useEffect(() => {
    if (availableDccs.length === 0) {
      return;
    }

    setQuickActionForms((prev) => ({
      ...prev,
      dccPublish: {
        ...prev.dccPublish,
        dccType: prev.dccPublish.dccType || availableDccs[0],
      },
    }));
  }, [availableDccs]);

  const handleStart = async (definition: ServiceDefinition): Promise<void> => {
    setServiceActions((prev) => ({ ...prev, [definition.key]: 'starting' }));
    try {
      await window.electron.invoke('python/start-service', {
        name: definition.name,
        args: definition.args,
      });
      await fetchServices();
    } catch (error) {
      console.error(`Failed to start ${definition.name}`, error);
      setServiceError(`Failed to start ${definition.name}.`);
    } finally {
      setServiceActions((prev) => ({ ...prev, [definition.key]: null }));
    }
  };

  const handleStop = async (definition: ServiceDefinition): Promise<void> => {
    const running = runningServicesByName.get(definition.name);
    if (!running) {
      setServiceError(`${definition.name} is not currently running.`);
      return;
    }

    setServiceActions((prev) => ({ ...prev, [definition.key]: 'stopping' }));
    try {
      await window.electron.invoke('python/stop-service', { id: running.id });
      await fetchServices();
    } catch (error) {
      console.error(`Failed to stop ${definition.name}`, error);
      setServiceError(`Failed to stop ${definition.name}.`);
    } finally {
      setServiceActions((prev) => ({ ...prev, [definition.key]: null }));
    }
  };

  const getActiveProjectName = (): string | null => {
    const projectName = quickActionForms.vendorIngest.project.trim() || currentProject?.name || '';
    return projectName || null;
  };

  const applyPresetForProject = (key: QuickActionKey, projectName: string): void => {
    const preset = config?.quickActionPresets?.[projectName];
    if (!preset) {
      return;
    }

    setQuickActionForms((prev) => {
      const nextForms: QuickActionForms = { ...prev };

      switch (key) {
        case 'vendorIngest': {
          nextForms.vendorIngest = {
            ...prev.vendorIngest,
            project: prev.vendorIngest.project || projectName,
            source: preset.vendorIngest?.sourcePath ?? prev.vendorIngest.source,
          };
          break;
        }
        case 'dccPublish': {
          const presetDccType = preset.dccPublish?.dccType;
          const resolvedDccType =
            presetDccType && availableDccs.includes(presetDccType as QuickActionForms['dccPublish']['dccType'])
              ? (presetDccType as QuickActionForms['dccPublish']['dccType'])
              : prev.dccPublish.dccType;

          nextForms.dccPublish = {
            ...prev.dccPublish,
            dccType: resolvedDccType,
            scenePath: preset.dccPublish?.lastScenePath ?? prev.dccPublish.scenePath,
          };
          break;
        }
        case 'submitRender': {
          nextForms.submitRender = {
            ...prev.submitRender,
            profileName: preset.renderSubmit?.profileName ?? prev.submitRender.profileName,
            frameRange: preset.renderSubmit?.lastFrameRange ?? prev.submitRender.frameRange,
          };
          break;
        }
        case 'packageDelivery': {
          nextForms.packageDelivery = {
            ...prev.packageDelivery,
            playlist: preset.clientDelivery?.playlistName ?? prev.packageDelivery.playlist,
            target: preset.clientDelivery?.targetPath ?? prev.packageDelivery.target,
          };
          break;
        }
        default:
          break;
      }

      return nextForms;
    });
  };

  const handleOpenQuickAction = (key: QuickActionKey): void => {
    if (!currentProject) {
      return;
    }

    if (key === 'vendorIngest') {
      setShowVendorIngestWizard(true);
      return;
    }

    if (key === 'dccPublish') {
      setShowDccPublishWizard(true);
      return;
    }

    if (key === 'packageDelivery') {
      setShowDeliveryWizard(true);
      return;
    }

    setActiveQuickAction(key);
    setActionStatus({ state: 'idle', stdout: '', stderr: '' });

    const projectName = getActiveProjectName();
    if (projectName) {
      applyPresetForProject(key, projectName);
    }
  };

  const handleCloseQuickAction = (): void => {
    setActiveQuickAction(null);
    setActionStatus({ state: 'idle', stdout: '', stderr: '' });
  };

  const updateQuickActionForm = <K extends QuickActionKey, F extends keyof QuickActionForms[K]>(
    key: K,
    field: F,
    value: QuickActionForms[K][F],
  ): void => {
    setQuickActionForms((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        [field]: value,
      },
    }));
  };

  const buildQuickActionArgs = (key: QuickActionKey): string[] => {
    switch (key) {
      case 'vendorIngest': {
        const { source, project } = quickActionForms.vendorIngest;
        return ['-m', 'onepiece', 'ingest', '--source', source, '--project', project];
      }
      case 'dccPublish': {
        const { dccType, scenePath } = quickActionForms.dccPublish;
        return ['-m', 'onepiece', 'dcc', 'publish', '--dcc', dccType, '--scene', scenePath];
      }
      case 'submitRender': {
        const { profileName, frameRange } = quickActionForms.submitRender;
        const args = ['-m', 'onepiece', 'render', 'submit', '--profile', profileName];
        const trimmedRange = frameRange.trim();

        if (trimmedRange) {
          args.push('--frames', trimmedRange);
        }

        return args;
      }
      case 'packageDelivery': {
        const { playlist, target } = quickActionForms.packageDelivery;
        return ['-m', 'onepiece', 'delivery', 'package', '--playlist', playlist, '--target', target];
      }
      default:
        return [];
    }
  };

  const buildQuickActionLabel = (key: QuickActionKey): string => {
    switch (key) {
      case 'vendorIngest': {
        const { source, project } = quickActionForms.vendorIngest;
        const projectName = project || currentProject?.name;
        return projectName ? `Vendor ingest for ${projectName} (${source})` : `Vendor ingest (${source})`;
      }
      case 'dccPublish': {
        const { dccType, scenePath } = quickActionForms.dccPublish;
        return `Publish ${scenePath || 'scene'} (${dccType || 'dcc'})`;
      }
      case 'submitRender': {
        const { profileName } = quickActionForms.submitRender;
        return `Render submit (${profileName || 'profile'})`;
      }
      case 'packageDelivery': {
        const { playlist } = quickActionForms.packageDelivery;
        return `Delivery package (${playlist || 'playlist'})`;
      }
      default:
        return 'Background task';
    }
  };

  const isQuickActionValid = (key: QuickActionKey): boolean => {
    switch (key) {
      case 'vendorIngest': {
        const { source, project } = quickActionForms.vendorIngest;
        return Boolean(source.trim() && project.trim());
      }
      case 'dccPublish': {
        const { dccType, scenePath } = quickActionForms.dccPublish;
        return Boolean(scenePath.trim() && dccType && availableDccs.includes(dccType));
      }
      case 'submitRender':
        return Boolean(quickActionForms.submitRender.profileName.trim());
      case 'packageDelivery': {
        const { playlist, target } = quickActionForms.packageDelivery;
        return Boolean(playlist.trim() && target.trim());
      }
      default:
        return false;
    }
  };

  const runQuickAction = async (): Promise<void> => {
    if (!activeQuickAction) {
      return;
    }

    if (!isQuickActionValid(activeQuickAction)) {
      setActionStatus({ state: 'error', stdout: '', stderr: '', error: 'Please fill in the required fields.' });
      return;
    }

    setActionStatus({ state: 'running', stdout: '', stderr: '' });

    try {
      const label = buildQuickActionLabel(activeQuickAction);
      const args = buildQuickActionArgs(activeQuickAction);

      const taskId = await window.electron.invoke<string>('tasks/create', {
        label,
        args,
      });

      setActionStatus({
        state: 'success',
        stdout: `Background task created (id: ${taskId}). Track progress in the Tasks tab.`,
        stderr: '',
      });

      showToast({
        kind: 'info',
        message: `Task started: ${label}`,
        actionLabel: onViewTasks ? 'View tasks' : undefined,
        onAction: onViewTasks,
      });

      const projectName = getActiveProjectName();
      if (projectName) {
        const existingPresets = config?.quickActionPresets ?? {};
        const existingProjectPreset = existingPresets[projectName] ?? {};
        const projectPresetUpdate: NonNullable<DesktopConfig['quickActionPresets']>[string] = {
          ...existingProjectPreset,
        };

        switch (activeQuickAction) {
          case 'vendorIngest': {
            projectPresetUpdate.vendorIngest = {
              sourcePath: quickActionForms.vendorIngest.source,
            };
            break;
          }
          case 'dccPublish': {
            projectPresetUpdate.dccPublish = {
              dccType: quickActionForms.dccPublish.dccType,
              lastScenePath: quickActionForms.dccPublish.scenePath,
            };
            break;
          }
          case 'submitRender': {
            projectPresetUpdate.renderSubmit = {
              profileName: quickActionForms.submitRender.profileName,
              lastFrameRange: quickActionForms.submitRender.frameRange,
            };
            break;
          }
          case 'packageDelivery': {
            projectPresetUpdate.clientDelivery = {
              playlistName: quickActionForms.packageDelivery.playlist,
              targetPath: quickActionForms.packageDelivery.target,
            };
            break;
          }
          default:
            break;
        }

        const quickActionPresets = {
          ...existingPresets,
          [projectName]: projectPresetUpdate,
        };

        try {
          const updatedConfig = await window.electron.invoke<DesktopConfig>('config/save', {
            quickActionPresets,
          });
          setConfig(updatedConfig);
        } catch (saveError) {
          console.error('Failed to persist quick action presets', saveError);
        }
      }
    } catch (err) {
      setActionStatus({
        state: 'error',
        stdout: '',
        stderr: '',
        error: err instanceof Error ? err.message : 'Failed to start task.',
      });
    }
  };

  const quickActionsDisabled = !currentProject;

  const runHealthCheck = async (): Promise<void> => {
    setHealthCheck({ running: true, exitCode: null, stdout: '', stderr: '' });
    setError(null);

    try {
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>(
        'python/run-command',
        { args: ['-m', 'onepiece', 'doctor'] },
      );

      const formatted = formatDoctorOutput(result.stdout, result.stderr, result.code);
      const hasError = !formatted.isOk || result.code !== 0;

      setHealthCheck({
        running: false,
        exitCode: result.code,
        stdout: result.stdout,
        stderr: result.stderr,
      });

      if (hasError) {
        const firstStderrLine = result.stderr.split('\n').find((line) => line.trim());
        setError({
          title: 'Health check reported issues',
          message: firstStderrLine ? firstStderrLine.trim().slice(0, 200) : formatted.summary,
          suggestedAction: 'Open logs',
        });
        showToast({
          kind: 'error',
          message: formatted.summary,
        });
      } else {
        showToast({ kind: 'success', message: 'Health check passed. Your workstation looks good.' });
      }
    } catch (err) {
      console.error('Health check failed to execute', err);
      setHealthCheck({
        running: false,
        exitCode: null,
        stdout: '',
        stderr: '',
        error: 'Failed to run health check.',
      });
      setError({
        title: 'Health check failed to run',
        message: err instanceof Error ? err.message : 'Unexpected error occurred.',
        suggestedAction: 'Check your Python path in Settings',
      });
      showToast({
        kind: 'error',
        message: 'Health check failed to run. Please review your Python path or logs.',
      });
    }
  };

  const openUtaDashboard = (): void => {
    const url = `http://localhost:${UTA_PORT}`;
    void window.electron.invoke('open-url', { url });
  };

  const renderServiceStatus = (definition: ServiceDefinition): JSX.Element => {
    const running = runningServicesByName.get(definition.name);
    const isRunning = Boolean(running);
    const actionState = serviceActions[definition.key];

    return (
      <Card key={definition.key}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: theme.spacing.md }}>
          <div style={{ display: 'grid', gap: theme.spacing.xs }}>
            <h3 style={{ margin: 0 }}>{definition.name}</h3>
            <p style={{ margin: 0, color: theme.colors.textMuted }}>{definition.description}</p>
          </div>
          <StatusBadge status={isRunning ? 'running' : 'stopped'}>
            {isRunning ? 'Running' : 'Stopped'}
          </StatusBadge>
        </div>

        <div style={{ display: 'flex', gap: theme.spacing.sm }}>
          <Button
            onClick={() => void handleStart(definition)}
            disabled={isRunning || actionState === 'starting'}
            isLoading={actionState === 'starting'}
          >
            Start
          </Button>
          <Button
            variant="secondary"
            onClick={() => void handleStop(definition)}
            disabled={!isRunning || actionState === 'stopping'}
            isLoading={actionState === 'stopping'}
          >
            Stop
          </Button>
        </div>
        {isRunning && running?.pid ? (
          <p style={{ margin: 0, color: theme.colors.textMuted }}>PID: {running.pid}</p>
        ) : null}
      </Card>
    );
  };

  const renderQuickActionModal = (): JSX.Element | null => {
    if (!activeQuickAction) {
      return null;
    }

    const action = QUICK_ACTIONS.find((item) => item.key === activeQuickAction);
    if (!action) {
      return null;
    }

    const isRunning = actionStatus.state === 'running';
    const canRun = isQuickActionValid(activeQuickAction) && !isRunning;

    const renderFields = (): JSX.Element => {
      switch (activeQuickAction) {
        case 'dccPublish':
          return (
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <label style={{ display: 'grid', gap: '0.35rem' }}>
                <span style={{ fontWeight: theme.typography.fontWeightMedium }}>DCC type</span>
                {availableDccs.length === 0 ? (
                  <p className="op-error">Enable a DCC in Settings to publish.</p>
                ) : (
                  <select
                    value={quickActionForms.dccPublish.dccType}
                    onChange={(event) =>
                      updateQuickActionForm('dccPublish', 'dccType', event.target.value as QuickActionForms['dccPublish']['dccType'])
                    }
                    style={{
                      padding: `${theme.spacing.sm} ${theme.spacing.md}`,
                      borderRadius: theme.radii.md,
                      border: `1px solid ${theme.colors.border}`,
                      background: theme.colors.surfaceAlt,
                    }}
                  >
                    <option value="">Select DCC</option>
                    {availableDccs.map((dcc) => (
                      <option key={dcc} value={dcc}>
                        {dcc.charAt(0).toUpperCase() + dcc.slice(1)}
                      </option>
                    ))}
                  </select>
                )}
              </label>
              <TextInput
                label="Path to scene file"
                placeholder="/path/to/scene.ext"
                value={quickActionForms.dccPublish.scenePath}
                onChange={(event) => updateQuickActionForm('dccPublish', 'scenePath', event.target.value)}
                required
              />
            </div>
          );
        case 'submitRender':
          return (
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <TextInput
                label="Render profile name"
                placeholder="profile-name"
                value={quickActionForms.submitRender.profileName}
                onChange={(event) => updateQuickActionForm('submitRender', 'profileName', event.target.value)}
                required
              />
              <TextInput
                label="Frame range (optional)"
                placeholder="1001-1100 or 1,3,5"
                value={quickActionForms.submitRender.frameRange}
                onChange={(event) => updateQuickActionForm('submitRender', 'frameRange', event.target.value)}
              />
            </div>
          );
        case 'packageDelivery':
          return (
            <div style={{ display: 'grid', gap: theme.spacing.sm }}>
              <TextInput
                label="Playlist / name"
                placeholder="Playlist or version name"
                value={quickActionForms.packageDelivery.playlist}
                onChange={(event) => updateQuickActionForm('packageDelivery', 'playlist', event.target.value)}
                required
              />
              <TextInput
                label="Target path or bucket"
                placeholder="/deliveries/client-x or s3://bucket/path"
                value={quickActionForms.packageDelivery.target}
                onChange={(event) => updateQuickActionForm('packageDelivery', 'target', event.target.value)}
                required
              />
            </div>
          );
        default:
          return <></>;
      }
    };

    return (
      <Modal
        isOpen
        onClose={handleCloseQuickAction}
        title={action.label}
        description={action.description}
        primaryAction={{
          label: isRunning ? 'Running…' : 'Run action',
          onClick: () => void runQuickAction(),
          disabled: !canRun || (activeQuickAction === 'dccPublish' && availableDccs.length === 0),
          isLoading: isRunning,
        }}
        secondaryAction={{ label: 'Cancel', onClick: handleCloseQuickAction, disabled: isRunning, variant: 'secondary' }}
      >
        <div style={{ display: 'grid', gap: theme.spacing.md }}>
          {renderFields()}
          <div
            style={{
              background: theme.colors.surface,
              border: `1px dashed ${theme.colors.border}`,
              borderRadius: theme.radii.md,
              padding: theme.spacing.sm,
              display: 'grid',
              gap: '0.35rem',
            }}
          >
            {actionStatus.state === 'running' ? (
              <p style={{ margin: 0, color: theme.colors.textMuted }}>Running…</p>
            ) : null}
            {actionStatus.state === 'success' ? (
              <p style={{ margin: 0, color: theme.colors.success }}>Command completed successfully.</p>
            ) : null}
            {actionStatus.state === 'error' && actionStatus.error ? (
              <p style={{ margin: 0, color: theme.colors.danger }}>{actionStatus.error}</p>
            ) : null}

            {actionStatus.stdout ? (
              <div>
                <h4 style={{ margin: '0 0 0.25rem' }}>Stdout</h4>
                <pre
                  style={{
                    background: theme.colors.surfaceAlt,
                    padding: theme.spacing.sm,
                    borderRadius: theme.radii.sm,
                    maxHeight: '220px',
                    overflow: 'auto',
                    margin: 0,
                    border: `1px solid ${theme.colors.border}`,
                  }}
                >
                  {actionStatus.stdout}
                </pre>
              </div>
            ) : null}
            {actionStatus.stderr ? (
              <div>
                <h4 style={{ margin: '0 0 0.25rem' }}>Stderr</h4>
                <pre
                  style={{
                    background: theme.colors.surfaceAlt,
                    padding: theme.spacing.sm,
                    borderRadius: theme.radii.sm,
                    maxHeight: '220px',
                    overflow: 'auto',
                    margin: 0,
                    border: `1px solid ${theme.colors.border}`,
                  }}
                >
                  {actionStatus.stderr}
                </pre>
              </div>
            ) : null}
          </div>
        </div>
      </Modal>
    );
  };

  const renderQuickActionsCard = (): JSX.Element => (
    <Card>
      <SectionHeader title="Quick Actions" subtitle="Wrap important OnePiece CLI workflows in simple prompts." />
      {!currentProject ? <p className="op-muted">Select a project to enable these actions.</p> : null}
      <div
        style={{
          display: 'grid',
          gap: theme.spacing.md,
          gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
        }}
      >
        {QUICK_ACTIONS.map((action) => (
          <Card key={action.key} title={action.label}>
            <p style={{ margin: 0, color: theme.colors.textMuted }}>{action.description}</p>
            <Button fullWidth onClick={() => handleOpenQuickAction(action.key)} disabled={quickActionsDisabled}>
              Launch
            </Button>
          </Card>
        ))}
      </div>
    </Card>
  );

  const renderServicesCard = (): JSX.Element => (
    <Card>
      <SectionHeader
        title="Services"
        subtitle="Start or stop the local stack components. Status is refreshed every 5 seconds."
        action={
          <Button variant="secondary" onClick={() => void fetchServices()}>
            Refresh status
          </Button>
        }
      />
      {serviceError ? <p className="op-error">{serviceError}</p> : null}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
          gap: theme.spacing.md,
        }}
      >
        {SERVICE_DEFINITIONS.map((definition) => renderServiceStatus(definition))}
      </div>
    </Card>
  );

  return (
    <div className="op-layout" style={{ display: 'flex', flexDirection: 'column', gap: theme.spacing.lg }}>
      {error ? (
        <div className="op-banner op-banner-error">
          <div>
            <strong>{error.title}</strong>
            <p className="op-banner-message">{error.message}</p>
          </div>
          <div className="op-banner-actions">
            <Button variant="secondary" onClick={() => onViewLogs?.()}>
              View logs
            </Button>
            <Button onClick={() => void runHealthCheck()} isLoading={healthCheck.running}>
              Retry health check
            </Button>
            <Button variant="ghost" onClick={() => setError(null)}>
              Dismiss
            </Button>
          </div>
          {error.suggestedAction ? <p className="op-banner-hint">{error.suggestedAction}</p> : null}
        </div>
      ) : null}
      <header className="op-header">
        <div>
          <p className="op-eyebrow">OnePiece Studio Desktop</p>
          <h1>Home</h1>
          <p>Manage your local services, run diagnostics, and open dashboards.</p>
        </div>
        <Button onClick={openUtaDashboard}>Open Uta Dashboard</Button>
      </header>

      <Card>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: theme.spacing.md,
            flexWrap: 'wrap',
          }}
        >
          <div>
            <p className="op-eyebrow">Project</p>
            <h2 style={{ margin: 0 }}>{currentProject ? currentProject.name : 'No project selected'}</h2>
            <p style={{ margin: '0.35rem 0 0', color: theme.colors.textMuted }}>
              {currentProject ? currentProject.path : 'Select a project to enable these actions.'}
            </p>
          </div>
        </div>
      </Card>

      <SectionHeader title="Health & Status" subtitle="See your configuration and run workstation checks." />
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))',
          gap: theme.spacing.lg,
        }}
      >
        <Card title="Current configuration">
          {config ? (
            <dl className="op-definition-list">
              <div>
                <dt>Profile</dt>
                <dd>{config.profile ?? 'Not set'}</dd>
              </div>
              <div>
                <dt>Project root</dt>
                <dd>{config.projectRoot ?? 'Not set'}</dd>
              </div>
              <div>
                <dt>Python path</dt>
                <dd>{config.pythonPath ?? 'Using system default'}</dd>
              </div>
            </dl>
          ) : (
            <p>Loading configuration…</p>
          )}
        </Card>

        <Card>
          <SectionHeader
            title="Health check"
            subtitle="Validate your workstation with the OnePiece doctor."
            action={
              <Button onClick={() => void runHealthCheck()} isLoading={healthCheck.running} disabled={healthCheck.running}>
                {healthCheck.running ? 'Running…' : 'Run health check'}
              </Button>
            }
          />
          {healthCheck.exitCode !== null && !healthCheck.running ? (
            <StatusBadge status={healthCheck.exitCode === 0 ? 'success' : 'error'}>
              {healthCheck.exitCode === 0 ? 'Doctor check passed' : 'Doctor check reported issues'}
            </StatusBadge>
          ) : null}
          {healthCheck.error ? <p className="op-error">{healthCheck.error}</p> : null}
          <div className="op-log-output">
            {healthCheck.stdout ? (
              <div>
                <h4>Stdout</h4>
                <pre>{healthCheck.stdout}</pre>
              </div>
            ) : null}
            {healthCheck.stderr ? (
              <div>
                <h4>Stderr</h4>
                <pre>{healthCheck.stderr}</pre>
              </div>
            ) : null}
            {!healthCheck.stdout && !healthCheck.stderr && !healthCheck.error ? (
              <p className="op-muted">Run the health check to see diagnostics.</p>
            ) : null}
          </div>
        </Card>
      </div>

        <div style={{ display: 'grid', gap: theme.spacing.md }}>
          <Tabs
            tabs={[
              { id: 'overview', label: 'Overview' },
              { id: 'services', label: 'Services' },
              { id: 'quickActions', label: 'Quick Actions' },
            ]}
            activeTabId={activeTab}
            onTabChange={(id) => setActiveTab(id as typeof activeTab)}
          />
          {activeTab === 'overview' ? <ProjectOverview project={currentProject} onViewLogs={onViewLogs} /> : null}
          {activeTab === 'services' ? renderServicesCard() : null}
          {activeTab === 'quickActions' ? renderQuickActionsCard() : null}
        </div>
        {renderQuickActionModal()}
        {showVendorIngestWizard ? (
          <VendorIngestWizard
            project={currentProject ?? undefined}
            onClose={() => setShowVendorIngestWizard(false)}
            onViewTasks={onViewTasks}
          />
        ) : null}
        {showDccPublishWizard ? (
          <DccPublishWizard
            project={currentProject ?? undefined}
            enabledDccs={availableDccs}
            onClose={() => setShowDccPublishWizard(false)}
          />
        ) : null}
        {showDeliveryWizard ? (
          <DeliveryWizard project={currentProject ?? undefined} onClose={() => setShowDeliveryWizard(false)} />
        ) : null}
    </div>
  );
}

export default HomeScreen;
