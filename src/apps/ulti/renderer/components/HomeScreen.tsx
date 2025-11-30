import React, { useEffect, useMemo, useState } from 'react';

interface DesktopConfig {
  hasCompletedWizard: boolean;
  createdAt: string;
  updatedAt: string;
  profile?: 'vfx' | 'archviz' | 'freelancer' | 'demo';
  pythonPath?: string;
  projectRoot?: string;
  dccs?: {
    maya?: { enabled: boolean; executablePath?: string };
    blender?: { enabled: boolean; executablePath?: string };
    unreal?: { enabled: boolean; executablePath?: string };
  };
}

type HomeScreenProps = {
  config?: DesktopConfig;
  onViewLogs?: () => void;
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

function HomeScreen({ config: initialConfig, onViewLogs }: HomeScreenProps): JSX.Element {
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
  const [actionStatus, setActionStatus] = useState<ActionStatus>({ state: 'idle', stdout: '', stderr: '' });

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

  const handleOpenQuickAction = (key: QuickActionKey): void => {
    setActiveQuickAction(key);
    setActionStatus({ state: 'idle', stdout: '', stderr: '' });

    if (key === 'dccPublish' && !quickActionForms.dccPublish.dccType && availableDccs[0]) {
      setQuickActionForms((prev) => ({
        ...prev,
        dccPublish: { ...prev.dccPublish, dccType: availableDccs[0] },
      }));
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
      const result = await window.electron.invoke<{ code: number; stdout: string; stderr: string }>(
        'python/run-command',
        { args: buildQuickActionArgs(activeQuickAction) },
      );

      const isSuccess = result.code === 0;
      setActionStatus({
        state: isSuccess ? 'success' : 'error',
        stdout: result.stdout,
        stderr: result.stderr,
        error: isSuccess ? undefined : `Command exited with code ${result.code}`,
      });
    } catch (err) {
      setActionStatus({
        state: 'error',
        stdout: '',
        stderr: '',
        error: err instanceof Error ? err.message : 'Failed to run command.',
      });
    }
  };

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
      <div key={definition.key} className="op-card op-service-card">
        <div className="op-service-header">
          <div>
            <h3>{definition.name}</h3>
            <p className="op-service-description">{definition.description}</p>
          </div>
          <span className={`op-status ${isRunning ? 'running' : 'stopped'}`}>
            {isRunning ? 'Running' : 'Stopped'}
          </span>
        </div>
        <div className="op-service-actions">
          <button
            type="button"
            className="op-primary"
            onClick={() => void handleStart(definition)}
            disabled={isRunning || actionState === 'starting'}
          >
            {actionState === 'starting' ? 'Starting…' : 'Start'}
          </button>
          <button
            type="button"
            className="op-secondary"
            onClick={() => void handleStop(definition)}
            disabled={!isRunning || actionState === 'stopping'}
          >
            {actionState === 'stopping' ? 'Stopping…' : 'Stop'}
          </button>
        </div>
        {isRunning && running?.pid ? <p className="op-service-meta">PID: {running.pid}</p> : null}
      </div>
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
        case 'vendorIngest':
          return (
            <div className="op-field-group">
              <label className="op-field required">
                <span>Source folder path</span>
                <input
                  type="text"
                  value={quickActionForms.vendorIngest.source}
                  onChange={(event) => updateQuickActionForm('vendorIngest', 'source', event.target.value)}
                  placeholder="/path/to/vendor/drop"
                />
              </label>
              <label className="op-field required">
                <span>Project/show name</span>
                <input
                  type="text"
                  value={quickActionForms.vendorIngest.project}
                  onChange={(event) => updateQuickActionForm('vendorIngest', 'project', event.target.value)}
                  placeholder="Project identifier"
                />
              </label>
            </div>
          );
        case 'dccPublish':
          return (
            <div className="op-field-group">
              <label className="op-field required">
                <span>DCC type</span>
                {availableDccs.length === 0 ? (
                  <p className="op-error">Enable a DCC in Settings to publish.</p>
                ) : (
                  <select
                    value={quickActionForms.dccPublish.dccType}
                    onChange={(event) =>
                      updateQuickActionForm('dccPublish', 'dccType', event.target.value as QuickActionForms['dccPublish']['dccType'])
                    }
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
              <label className="op-field required">
                <span>Path to scene file</span>
                <input
                  type="text"
                  value={quickActionForms.dccPublish.scenePath}
                  onChange={(event) => updateQuickActionForm('dccPublish', 'scenePath', event.target.value)}
                  placeholder="/path/to/scene.ext"
                />
              </label>
            </div>
          );
        case 'submitRender':
          return (
            <div className="op-field-group">
              <label className="op-field required">
                <span>Render profile name</span>
                <input
                  type="text"
                  value={quickActionForms.submitRender.profileName}
                  onChange={(event) => updateQuickActionForm('submitRender', 'profileName', event.target.value)}
                  placeholder="profile-name"
                />
              </label>
              <label className="op-field">
                <span>Frame range (optional)</span>
                <input
                  type="text"
                  value={quickActionForms.submitRender.frameRange}
                  onChange={(event) => updateQuickActionForm('submitRender', 'frameRange', event.target.value)}
                  placeholder="1001-1100 or 1,3,5"
                />
              </label>
            </div>
          );
        case 'packageDelivery':
          return (
            <div className="op-field-group">
              <label className="op-field required">
                <span>Playlist / name</span>
                <input
                  type="text"
                  value={quickActionForms.packageDelivery.playlist}
                  onChange={(event) => updateQuickActionForm('packageDelivery', 'playlist', event.target.value)}
                  placeholder="Playlist or version name"
                />
              </label>
              <label className="op-field required">
                <span>Target path or bucket</span>
                <input
                  type="text"
                  value={quickActionForms.packageDelivery.target}
                  onChange={(event) => updateQuickActionForm('packageDelivery', 'target', event.target.value)}
                  placeholder="/deliveries/client-x or s3://bucket/path"
                />
              </label>
            </div>
          );
        default:
          return <></>;
      }
    };

    return (
      <div className="op-modal-backdrop" role="dialog" aria-modal="true" aria-labelledby="quick-action-title">
        <div className="op-modal">
          <div className="op-modal__header">
            <div>
              <p className="op-eyebrow">Quick action</p>
              <h3 id="quick-action-title">{action.label}</h3>
              <p className="op-muted">{action.description}</p>
            </div>
            <button type="button" className="op-tertiary" onClick={handleCloseQuickAction}>
              Close
            </button>
          </div>

          <div className="op-modal__body">
            {renderFields()}
            <div className="op-modal__status">
              {actionStatus.state === 'running' ? <p className="op-muted">Running…</p> : null}
              {actionStatus.state === 'success' ? <p className="op-success">Command completed successfully.</p> : null}
              {actionStatus.state === 'error' && actionStatus.error ? (
                <p className="op-error">{actionStatus.error}</p>
              ) : null}

              {actionStatus.stdout ? (
                <div>
                  <h4>Stdout</h4>
                  <pre>{actionStatus.stdout}</pre>
                </div>
              ) : null}
              {actionStatus.stderr ? (
                <div>
                  <h4>Stderr</h4>
                  <pre>{actionStatus.stderr}</pre>
                </div>
              ) : null}
            </div>
          </div>

          <div className="op-modal__footer">
            <button type="button" className="op-secondary" onClick={handleCloseQuickAction} disabled={isRunning}>
              Cancel
            </button>
            <button
              type="button"
              className="op-primary"
              onClick={() => void runQuickAction()}
              disabled={!canRun || (activeQuickAction === 'dccPublish' && availableDccs.length === 0)}
            >
              {isRunning ? 'Running…' : 'Run action'}
            </button>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="op-layout">
      {error ? (
        <div className="op-banner op-banner-error">
          <div>
            <strong>{error.title}</strong>
            <p className="op-banner-message">{error.message}</p>
          </div>
          <div className="op-banner-actions">
            <button type="button" className="op-secondary" onClick={() => onViewLogs?.()}>
              View logs
            </button>
            <button type="button" className="op-primary" onClick={() => void runHealthCheck()}>
              Retry health check
            </button>
            <button type="button" className="op-tertiary" onClick={() => setError(null)}>
              Dismiss
            </button>
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
        <button type="button" className="op-primary" onClick={openUtaDashboard}>
          Open Uta Dashboard
        </button>
      </header>

      <section className="op-grid">
        <div className="op-card">
          <h2>Current configuration</h2>
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
        </div>

        <div className="op-card">
          <div className="op-card-header">
            <h2>Health check</h2>
            <button type="button" className="op-primary" onClick={() => void runHealthCheck()} disabled={healthCheck.running}>
              {healthCheck.running ? 'Running…' : 'Run health check'}
            </button>
          </div>
          {healthCheck.exitCode !== null && !healthCheck.running ? (
            <div className={`op-badge ${healthCheck.exitCode === 0 ? 'success' : 'error'}`}>
              {healthCheck.exitCode === 0 ? 'Doctor check passed' : 'Doctor check reported issues'}
            </div>
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
        </div>
      </section>

      <section className="op-card">
        <div className="op-card-header">
          <div>
            <h2>Quick Actions</h2>
            <p>Wrap important OnePiece CLI workflows in simple prompts.</p>
          </div>
        </div>
        <div className="op-quick-actions-grid">
          {QUICK_ACTIONS.map((action) => (
            <div key={action.key} className="op-quick-action">
              <div>
                <h3>{action.label}</h3>
                <p className="op-muted">{action.description}</p>
              </div>
              <button type="button" className="op-primary" onClick={() => handleOpenQuickAction(action.key)}>
                Launch
              </button>
            </div>
          ))}
        </div>
      </section>

      <section>
        <div className="op-section-header">
          <div>
            <h2>Services</h2>
            <p>Start or stop the local stack components. Status is refreshed every 5 seconds.</p>
          </div>
          <button type="button" className="op-secondary" onClick={() => void fetchServices()}>
            Refresh status
          </button>
        </div>
        {serviceError ? <p className="op-error">{serviceError}</p> : null}
        <div className="op-service-grid">
          {SERVICE_DEFINITIONS.map((definition) => renderServiceStatus(definition))}
        </div>
      </section>
      {renderQuickActionModal()}
    </div>
  );
}

export default HomeScreen;
